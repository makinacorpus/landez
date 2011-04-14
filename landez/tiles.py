import os
import re
import urllib
import shutil
from math import pi, cos, sin, log, exp, atan
import logging
import tempfile

from mbutil import disk_to_mbtiles

has_mapnik = False
try:
    import mapnik
    has_mapnik = True
except ImportError:
    pass


""" Default tiles URL """
DEFAULT_TILES_URL = "http://tile.cloudmade.com/f1fe9c2761a15118800b210c0eda823c/1/{size}/{z}/{x}/{y}.png"  # Register
""" Base temporary folder for building MBTiles files """
DEFAULT_TMP_DIR = tempfile.gettempdir()
""" Base folder for sharing tiles between different runs """
DEFAULT_TILES_DIR = DEFAULT_TMP_DIR
""" Default output MBTiles file """
DEFAULT_FILEPATH = os.path.join(os.getcwd(), "tiles.mbtiles")
""" Default tile size in pixels (*useless* in remote rendering) """
DEFAULT_TILE_SIZE = 256
""" Number of retries for remove tiles downloading """
DOWNLOAD_RETRIES = 3

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi


logger = logging.getLogger(__name__)


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a


class DownloadError(Exception):
    """ Raised when download at tiles URL fails DOWNLOAD_RETRIES times """
    pass

class GoogleProjection(object):
    """
    Transform Lon/Lat to Pixel within tiles
    Originally written by OSM team : http://svn.openstreetmap.org/applications/rendering/mapnik/generate_tiles.py     
    """
    def __init__(self, tilesize, levels = [0]):
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        self.maxlevel = max(levels) + 1
        c = tilesize
        for d in range(self.maxlevel):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
    
    def fromLLtoPixel(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def fromPixelToLL(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)


class MBTilesBuilder(object):
    def __init__(self, **kwargs):
        """
        A MBTiles builder, either from remote tiles or local mapnik rendering.

        Keyword arguments:
        remote -- use remote tiles (default True)
        stylefile -- mapnik stylesheet file, only necessary if `remote` is `False`
        cache -- use a local cache to share tiles between runs (default True)
        filepath -- output MBTiles file (default DEFAULT_FILEPATH)
        tmp_dir -- temporary folder for gathering tiles (default DEFAULT_TMP_DIR)
        tiles_url -- remote URL to download tiles (default DEFAULT_TILES_URL)
        tile_size -- default tile size (default DEFAULT_TILE_SIZE)
        tiles_dir -- Local folder containing existing tiles, and 
                     where cached tiles will be stored (default DEFAULT_TILES_DIR)
        """
        self.remote = kwargs.get('remote', True)
        self.stylefile = kwargs.get('stylefile')
        if not self.remote:
            assert has_mapnik, "Cannot render tiles without mapnik !"
            assert self.stylefile, "A mapnik stylesheet is required"
        
        self.filepath = kwargs.get('filepath', DEFAULT_FILEPATH)
        self.basename, ext = os.path.splitext(os.path.basename(self.filepath))
        
        self.tmp_dir = kwargs.get('tmp_dir', DEFAULT_TMP_DIR)
        self.tmp_dir = os.path.join(self.tmp_dir, self.basename)
        
        self.cache = kwargs.get('cache', True)
        self.tiles_dir = kwargs.get('tiles_dir', DEFAULT_TILES_DIR)
        self.tiles_url = kwargs.get('tiles_url', DEFAULT_TILES_URL)
        self.tile_size = kwargs.get('tile_size', DEFAULT_TILE_SIZE)
        
        self.proj = GoogleProjection(self.tile_size)
        self._bboxes = []
        self._mapnik = None
        self._prj = None

        # Number of tiles rendered/downloaded here
        self.rendered = 0
        # Number of tiles in total
        self.nbtiles = 0

    def add_coverage(self, bbox, zoomlevels):
        """
        Add a coverage
        """
        self._bboxes.append((bbox, zoomlevels))

    def tileslist(self, bbox, zoomlevels):
        """
        Build the tiles list within the bbox (minx, miny, maxx, maxy) at the specified zoom levels.
        Return a list of tuples (z,x,y)
        """
        if max(zoomlevels) >= self.proj.maxlevel:
            self.proj = GoogleProjection(self.tile_size, zoomlevels)
        
        ll0 = (bbox[0],bbox[3])
        ll1 = (bbox[2],bbox[1])

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

    def run(self, force=False):
        """
        Build a MBTile file, only if it does not exist.
        """
        if os.path.exists(self.filepath):
            if force:
                logger.warn("%s already exists. Overwrite." % self.filepath)
            else:
                # Already built, do not do anything.
                logger.info("%s already exists. Nothing to do." % self.filepath)
                return
        
        # Clean previous runs
        self.clean(full=force)
        
        # Compute list of tiles
        tileslist = set()
        for bbox, levels in self._bboxes:
            logger.debug("Compute list of tiles for bbox %s on zooms %s." % (bbox, levels))
            tileslist = tileslist.union(self.tileslist(bbox, levels))
        self.nbtiles = len(tileslist)
        logger.debug("%s tiles to be packaged." % self.nbtiles)

        # Go through whole list of tiles and gather them in tmp_dir
        self.rendered = 0
        for (z, x, y) in tileslist:
            self.prepare_tile((z, x, y))
        logger.debug("%s tiles were missing." % self.rendered)

        # Package it! 
        logger.info("Build MBTiles file '%s'." % self.filepath)
        disk_to_mbtiles(self.tmp_dir, self.filepath)
        self.clean()

    def clean(self, full=False):
        """
        Remove temporary directory and destination MBTile if full = True
        """
        logger.debug("Clean-up %s" % self.tmp_dir)
        try:
            shutil.rmtree(self.tmp_dir)
        except OSError:
            pass
        try:
            if full:
                logger.debug("Delete %s" % self.filepath)
                os.remove(self.filepath)
        except OSError:
            pass

    def prepare_tile(self, (z, x, y)):
        """
        Check already rendered tiles in `tiles_dir`, and copy them in the
        same temporary directory.
        """
        tile_dir = os.path.join("%s" % z, "%s" % x)
        tile_name = "%s.png" % y
        tile_path = os.path.join(tile_dir, tile_name)
        
        # Folder of tile is either cache or temporary
        tmp_dir = os.path.join(self.tmp_dir, tile_dir)        
        tile_abs_dir = tmp_dir
        if self.cache:
            tile_abs_dir = os.path.join(self.tiles_dir, tile_dir)
        # Full path of tile
        tile_abs_uri = os.path.join(tile_abs_dir, tile_name)

        # Render missing tiles !
        if self.cache and os.path.exists(tile_abs_uri):
            logger.debug("Found %s" % tile_abs_uri)
        else:
            if not os.path.isdir(tile_abs_dir):
                os.makedirs(tile_abs_dir)
            if self.remote:
                logger.debug("Download tile %s" % tile_path)
                self.download_tile(tile_abs_uri, z, x, y)
            else:
                logger.debug("Render tile %s" % tile_path)
                self.render_tile(tile_abs_uri, z, x, y)
            self.rendered += 1

        # If taken or rendered in cache, copy it to temporary dir
        if self.cache:
            if not os.path.isdir(tmp_dir):
                os.makedirs(tmp_dir)
            shutil.copy(tile_abs_uri, tmp_dir)

    def download_tile(self, output, z, x, y):
        """
        Download the specified tile from `tiles_url`
        """
        # Render each keyword in URL ({x}, {y}, {z}, {size} ... )
        size = self.tile_size
        try:
            url = self.tiles_url.format(**locals())
        except KeyError, e:
            raise DownloadError("Unknown keyword %s in URL" % e)
        
        logger.debug("Retrieve tile at %s" % url)
        r = DOWNLOAD_RETRIES
        while r > 0:
            try:
                image = urllib.URLopener()
                image.retrieve(url, output)
                return  # Done.
            except IOError, e:
                logger.debug("Download error, retry (%s left). (%s)" % (r, e))
                r -= 1
        raise DownloadError

    def render_tile(self, output, z, x, y):
        """
        Render the specified tile with Mapnik
        """
        if not self._mapnik:
            self._mapnik = mapnik.Map(self.tile_size, self.tile_size)
            # Load style XML
            mapnik.load_map(self._mapnik, self.stylefile, True)
            # Obtain <Map> projection
            self._prj = mapnik.Projection(self._mapnik.srs)

        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * self.tile_size, (y + 1) * self.tile_size)
        p1 = ((x + 1) * self.tile_size, y * self.tile_size)

        # Convert to LatLong (EPSG:4326)
        l0 = self.proj.fromPixelToLL(p0, z);
        l1 = self.proj.fromPixelToLL(p1, z);

        # Convert to map projection
        c0 = self._prj.forward(mapnik.Coord(l0[0],l0[1]))
        c1 = self._prj.forward(mapnik.Coord(l1[0],l1[1]))

        # Bounding box for the tile
        if hasattr(mapnik,'mapnik_version') and mapnik.mapnik_version() >= 800:
            bbox = mapnik.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik.Envelope(c0.x,c0.y, c1.x,c1.y)
        
        self._mapnik.resize(self.tile_size, self.tile_size)
        self._mapnik.zoom_to_box(bbox)
        self._mapnik.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik.Image(self.tile_size, self.tile_size)
        mapnik.render(self._mapnik, im)
        im.save(output, 'png256')
