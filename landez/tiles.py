import os
import re
import urllib
import shutil
import logging
import tempfile
import sqlite3
from gettext import gettext as _

from mbutil import disk_to_mbtiles

from proj import GoogleProjection
from reader import MBTilesReader

has_mapnik = False
try:
    import mapnik
    has_mapnik = True
except ImportError:
    pass

has_pil = False
try:
    import Image
    has_pil = True
except ImportError:
    try:
        from PIL import Image
        has_pil = True
    except ImportError:
        pass


""" Default tiles URL """
DEFAULT_TILES_URL = "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
""" Default tiles subdomains """
DEFAULT_TILES_SUBDOMAINS = list("abc")
""" Base temporary folder for building MBTiles files """
DEFAULT_TMP_DIR = os.path.join(tempfile.gettempdir(), 'landez')
""" Base folder for sharing tiles between different runs """
DEFAULT_TILES_DIR = DEFAULT_TMP_DIR
""" Default output MBTiles file """
DEFAULT_FILEPATH = os.path.join(os.getcwd(), "tiles.mbtiles")
""" Default tile size in pixels (*useless* in remote rendering) """
DEFAULT_TILE_SIZE = 256
""" Number of retries for remove tiles downloading """
DOWNLOAD_RETRIES = 3


logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """ Raised when download at tiles URL fails DOWNLOAD_RETRIES times """
    pass

class EmptyCoverageError(Exception):
    """ Raised when coverage (tiles list) is empty """
    pass

class InvalidCoverageError(Exception):
    """ Raised when coverage bounds are invalid """
    pass


class TilesManager(object):
   
    def __init__(self, **kwargs):
        """
        Manipulates tiles in general. Gives ability to list required tiles on a 
        bounding box, download them, render them, extract them from other mbtiles...
        
        Keyword arguments:
        remote -- use remote tiles (default True)
        stylefile -- mapnik stylesheet file, only necessary if `remote` is `False`
        cache -- use a local cache to share tiles between runs (default True)

        tmp_dir -- temporary folder for gathering tiles (default DEFAULT_TMP_DIR)
        tiles_url -- remote URL to download tiles (default DEFAULT_TILES_URL)
        tile_size -- default tile size (default DEFAULT_TILE_SIZE)
        tiles_dir -- Local folder containing existing tiles, and 
                     where cached tiles will be stored (default DEFAULT_TILES_DIR)
        mbtiles_file -- A MBTiles providing tiles (overrides ``tiles_url``)
        """
        self.remote = kwargs.get('remote', True)
        self.stylefile = kwargs.get('stylefile')

        self.tmp_dir = kwargs.get('tmp_dir', DEFAULT_TMP_DIR)
        
        self.cache = kwargs.get('cache', True)
        self.tiles_dir = kwargs.get('tiles_dir', DEFAULT_TILES_DIR)
        self.tiles_url = kwargs.get('tiles_url', DEFAULT_TILES_URL)
        self.tiles_subdomains = kwargs.get('tiles_subdomains', DEFAULT_TILES_SUBDOMAINS)
        self.tile_size = kwargs.get('tile_size', DEFAULT_TILE_SIZE)
        
        self.mbtiles_file = kwargs.get('mbtiles_file')
        if self.mbtiles_file:
            self.remote = False
        
        if not self.remote and not self.mbtiles_file:
            assert has_mapnik, _("Cannot render tiles without mapnik !")
            assert self.stylefile, _("A mapnik stylesheet is required")
        
        self.proj = GoogleProjection(self.tile_size)
        self._mapnik = None
        self._prj = None

        # Number of tiles rendered/downloaded here
        self.rendered = 0

    def tileslist(self, bbox, zoomlevels):
        """
        Build the tiles list within the bottom-left/top-right bounding 
        box (minx, miny, maxx, maxy) at the specified zoom levels.
        Return a list of tuples (z,x,y)
        """
        if len(bbox) != 4 or len(zoomlevels) == 0:
            raise InvalidCoverageError(_("Wrong format of bounding box or zoom levels."))

        xmin, ymin, xmax, ymax = bbox
        if abs(xmin) > 180 or abs(xmax) > 180 or \
           abs(ymin) > 90 or abs(ymax) > 90:
            raise InvalidCoverageError(_("Some coordinates exceed [-180,+180], [-90, 90]."))
        
        if xmin >= xmax or ymin >= ymax:
            raise InvalidCoverageError(_("Bounding box format is (xmin, ymin, xmax, ymax)"))
        
        if max(zoomlevels) >= self.proj.maxlevel:
            self.proj = GoogleProjection(self.tile_size, zoomlevels)
        
        ll0 = (xmin, ymax)  # left top
        ll1 = (xmax, ymin)  # right bottom

        l = []
        for z in zoomlevels:
            px0 = self.proj.fromLLtoPixel(ll0,z)
            px1 = self.proj.fromLLtoPixel(ll1,z)
            
            for x in range(int(px0[0]/self.tile_size),
                           int(px1[0]/self.tile_size)+1):
                if (x < 0) or (x >= 2**z):
                    continue
                for y in range(int(px0[1]/self.tile_size),
                               int(px1[1]/self.tile_size)+1):
                    if (y < 0) or (y >= 2**z):
                        continue
                    l.append((z, x, y))
        return l

    def tile_file(self, (z, x, y)):
        """
        Return folder (``z/x``) and name (``y.png``) for the specified tuple.
        """
        tile_dir = os.path.join("%s" % z, "%s" % x)
        y_mercator = (2**z - 1) - y
        tile_name = "%s.png" % y_mercator
        return tile_dir, tile_name

    def tile_fullpath(self, (z, x, y)):
        """
        Return the full path to the tile for the specified tuple (either cache or temporary)
        """
        tile_dir, tile_name = self.tile_file((z, x, y))
        # Folder of tile is either cache or temporary
        if self.cache:
            tile_abs_dir = os.path.join(self.tiles_dir, tile_dir)
        else:
            tile_abs_dir = os.path.join(self.tmp_dir, tile_dir)
        # Full path of tile
        return os.path.join(tile_abs_dir, tile_name)
        
    def prepare_tile(self, (z, x, y)):
        """
        Check already rendered tiles in `tiles_dir`, and copy them in the
        same temporary directory.
        """
        tile_dir, tile_name = self.tile_file((z, x, y))
        tile_path = os.path.join(tile_dir, tile_name)
        tile_abs_uri = self.tile_fullpath((z, x, y))
        tile_abs_dir = os.path.dirname(tile_abs_uri)
        
        # Render missing tiles !
        if self.cache and os.path.exists(tile_abs_uri):
            logger.debug(_("Found %s") % tile_abs_uri)
        else:
            if not os.path.isdir(tile_abs_dir):
                os.makedirs(tile_abs_dir)
            if self.remote:
                logger.debug(_("Download tile %s") % tile_path)
                self.download_tile(tile_abs_uri, z, x, y)
            else:
                if self.mbtiles_file:
                    logger.debug(_("Extract tile %s") % tile_path)
                    self.extract_tile(tile_abs_uri, z, x, y)
                else:
                    logger.debug(_("Render tile %s") % tile_path)
                    self.render_tile(tile_abs_uri, z, x, y)
            self.rendered += 1

        # If taken or rendered in cache, copy it to temporary dir
        if self.cache and self.tmp_dir != self.tiles_dir:
            tmp_dir = os.path.join(self.tmp_dir, tile_dir)
            if not os.path.isdir(tmp_dir):
                os.makedirs(tmp_dir)
            shutil.copy(tile_abs_uri, tmp_dir)

    def extract_tile(self, output, z, x, y):
        """
        Extract the specified tile from ``mbtiles_file``.
        """
        reader = MBTilesReader(self.mbtiles_file, self.tile_size)
        with open(output, 'wb') as f:
            f.write(reader.tile(z, x, y))

    def download_tile(self, output, z, x, y):
        """
        Download the specified tile from `tiles_url`
        """
        # Render each keyword in URL ({s}, {x}, {y}, {z}, {size} ... )
        size = self.tile_size
        s = self.tiles_subdomains[(x + y) % len(self.tiles_subdomains)];
        try:
            url = self.tiles_url.format(**locals())
        except KeyError, e:
            raise DownloadError(_("Unknown keyword %s in URL") % e)
        
        logger.debug(_("Retrieve tile at %s") % url)
        r = DOWNLOAD_RETRIES
        while r > 0:
            try:
                image = urllib.URLopener()
                image.retrieve(url, output)
                return  # Done.
            except IOError, e:
                logger.debug(_("Download error, retry (%s left). (%s)") % (r, e))
                r -= 1
        raise DownloadError

    def render_tile(self, output, z, x, y):
        """
        Render the specified tile with Mapnik
        """
        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * self.tile_size, (y + 1) * self.tile_size)
        p1 = ((x + 1) * self.tile_size, y * self.tile_size)
        # Convert to LatLong (EPSG:4326)
        l0 = self.proj.fromPixelToLL(p0, z)
        l1 = self.proj.fromPixelToLL(p1, z)
        return self.render(self.stylefile, 
                           (l0[0], l0[1], l1[0], l1[1]), 
                           output, 
                           self.tile_size, self.tile_size)

    def render(self, stylefile, bbox, output, width, height):
        """
        Render the specified bbox (minx, miny, maxx, maxy) with Mapnik
        """
        if not self._mapnik:
            self._mapnik = mapnik.Map(width, height)
            # Load style XML
            mapnik.load_map(self._mapnik, stylefile, True)
            # Obtain <Map> projection
            self._prj = mapnik.Projection(self._mapnik.srs)

        # Convert to map projection
        assert len(bbox) == 4, _("Provide a bounding box tuple (minx, miny, maxx, maxy)")
        c0 = self._prj.forward(mapnik.Coord(bbox[0],bbox[1]))
        c1 = self._prj.forward(mapnik.Coord(bbox[2],bbox[3]))

        # Bounding box for the tile
        if hasattr(mapnik,'mapnik_version') and mapnik.mapnik_version() >= 800:
            bbox = mapnik.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik.Envelope(c0.x,c0.y, c1.x,c1.y)
        
        self._mapnik.resize(width, height)
        self._mapnik.zoom_to_box(bbox)
        self._mapnik.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik.Image(width, height)
        mapnik.render(self._mapnik, im)
        im.save(output, 'png256')

    def clean(self):
        """
        Remove temporary directory and destination MBTile if full = True
        """
        logger.debug(_("Clean-up %s") % self.tmp_dir)
        try:
            shutil.rmtree(self.tmp_dir)
            # Delete parent folder only if empty
            try:
                parent = os.path.dirname(self.tmp_dir)
                os.rmdir(parent)
                logger.debug(_("Clean-up parent %s") % parent)
            except OSError:
                pass
        except OSError:
            pass


class MBTilesBuilder(TilesManager):
    def __init__(self, **kwargs):
        """
        A MBTiles builder for a list of bounding boxes and zoom levels.

        filepath -- output MBTiles file (default DEFAULT_FILEPATH)
        """
        super(MBTilesBuilder, self).__init__(**kwargs)
        self.filepath = kwargs.get('filepath', DEFAULT_FILEPATH)
        self.basename, ext = os.path.splitext(os.path.basename(self.filepath))
        self.tmp_dir = os.path.join(self.tmp_dir, self.basename)
        self.tiles_dir = kwargs.get('tiles_dir', self.tmp_dir)
        # Number of tiles in total
        self.nbtiles = 0
        self._bboxes = []

    def add_coverage(self, bbox, zoomlevels):
        """
        Add a coverage to be included in the resulting mbtiles file.
        """
        self._bboxes.append((bbox, zoomlevels))

    def run(self, force=False):
        """
        Build a MBTile file, only if it does not exist.
        """
        if os.path.exists(self.filepath):
            if force:
                logger.warn(_("%s already exists. Overwrite.") % self.filepath)
            else:
                # Already built, do not do anything.
                logger.info(_("%s already exists. Nothing to do.") % self.filepath)
                return
        
        # Clean previous runs
        self.clean(full=force)
        
        # Compute list of tiles
        tileslist = set()
        for bbox, levels in self._bboxes:
            logger.debug(_("Compute list of tiles for bbox %s on zooms %s.") % (bbox, levels))
            bboxlist = self.tileslist(bbox, levels)
            logger.debug(_("Add %s tiles.") % len(bboxlist))
            tileslist = tileslist.union(bboxlist)
            logger.debug(_("%s tiles in total.") % len(tileslist))
        self.nbtiles = len(tileslist)
        if not self.nbtiles:
            raise EmptyCoverageError(_("No tiles are covered by bounding boxes : %s") % self._bboxes)
        logger.debug(_("%s tiles to be packaged.") % self.nbtiles)

        # Go through whole list of tiles and gather them in tmp_dir
        self.rendered = 0
        for (z, x, y) in tileslist:
            self.prepare_tile((z, x, y))
        logger.debug(_("%s tiles were missing.") % self.rendered)

        # Package it! 
        logger.info(_("Build MBTiles file '%s'.") % self.filepath)
        disk_to_mbtiles(self.tmp_dir, self.filepath)
        self.clean()

    def clean(self, full=False):
        """
        Remove temporary directory and destination MBTile if full = True
        """
        super(MBTilesBuilder, self).clean()
        try:
            if full:
                logger.debug(_("Delete %s") % self.filepath)
                os.remove(self.filepath)
                os.remove("%s-journal" % self.filepath)
        except OSError:
            pass


class ImageExporter(TilesManager):
    def __init__(self, **kwargs):
        """
        Arrange the tiles and join them together to build a single big image.
        """
        super(ImageExporter, self).__init__(**kwargs)

    def grid_tiles(self, bbox, zoomlevel):
        """
        Return a grid of (x, y) tuples representing the juxtaposition 
        of tiles on the specified ``bbox`` at the specified ``zoomlevel``.
        """
        tiles = self.tileslist(bbox, [zoomlevel])
        grid = {}
        for (z, x, y) in tiles:
            if not grid.get(y):
                grid[y] = []
            grid[y].append(x)
        sortedgrid = []
        for y in sorted(grid.keys()):
            sortedgrid.append([(x, y) for x in sorted(grid[y])])
        return sortedgrid

    def export_image(self, bbox, zoomlevel, imagepath):
        """
        Writes to ``imagepath`` the tiles for the specified bounding box and zoomlevel.
        """
        assert has_pil, _("Cannot export image without python PIL")
        grid = self.grid_tiles(bbox, zoomlevel)
        width = len(grid[0])
        height = len(grid)
        widthpix = width * self.tile_size
        heightpix = height * self.tile_size
        
        result = Image.new("RGBA", (widthpix, heightpix))
        offset = (0, 0)
        for i, row in enumerate(grid):
            for j, (x, y) in enumerate(row):
                offset = (j * self.tile_size, i * self.tile_size)
                tile_path = self.tile_fullpath((zoomlevel, x, y))
                self.prepare_tile((zoomlevel, x, y))
                img = Image.open(tile_path)
                result.paste(img, offset)
        result.save(imagepath)
        self.clean()
