import os
import re
import shutil
import logging
from gettext import gettext as _
import json

from mbutil import disk_to_mbtiles

from . import (DEFAULT_TILES_URL, DEFAULT_TILES_SUBDOMAINS, 
               DEFAULT_TMP_DIR, DEFAULT_TILES_DIR, DEFAULT_FILEPATH,
               DEFAULT_TILE_SIZE, DOWNLOAD_RETRIES)
from proj import GoogleProjection
from reader import (MBTilesReader, TileDownloader, WMSReader, 
                    MapnikRenderer, ExtractionError, DownloadError)

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


logger = logging.getLogger(__name__)



class EmptyCoverageError(Exception):
    """ Raised when coverage (tiles list) is empty """
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
        
        self.wms_server = kwargs.get('wms_server')
        self.wms_layers = kwargs.get('wms_layers', [])
        self.wms_options = kwargs.get('wms_options', {})
        
        if self.mbtiles_file:
            self.reader = MBTilesReader(self.mbtiles_file, self.tile_size)
        elif self.wms_server:
            assert self.wms_layers, _("Request at least one layer")
            self.reader = WMSReader(self.wms_server, self.wms_layers, 
                                    self.tile_size, **self.wms_options)
        elif not self.remote:
            assert has_mapnik, _("Cannot render tiles without mapnik !")
            assert self.stylefile, _("A mapnik stylesheet is required")
            self.reader = MapnikRenderer(self.stylefile, self.tile_size)
        else:
            self.reader = TileDownloader(self.tiles_url, self.tile_size)

        basename = re.sub(r'[^a-z^A-Z^0-9]+', '', self.reader.basename)
        self.tmp_dir = os.path.join(self.tmp_dir, basename)
        self.tiles_dir = os.path.join(self.tiles_dir, basename)
        self._layers = []
        # Number of tiles rendered/downloaded here
        self.rendered = 0

    def tileslist(self, bbox, zoomlevels):
        """
        Build the tiles list within the bottom-left/top-right bounding 
        box (minx, miny, maxx, maxy) at the specified zoom levels.
        Return a list of tuples (z,x,y)
        """
        proj = GoogleProjection(self.tile_size, zoomlevels)
        return proj.tileslist(bbox)

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

    def add_layer(self, tilemanager):
        """
        Add a layer to be blended (alpha-composite) on top of the tile.
        tilemanager -- a `TileManager` instance
        """
        assert has_pil, _("Cannot blend layers without python PIL")
        assert self.tile_size == tilemanager.tile_size, _("Cannot blend layers whose tile size differs")
        self._layers.append(tilemanager)

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
            self.reader.tile(z, x, y, tile_abs_uri)
            self.rendered += 1

        # Blend layers
        if len(self._layers) > 0:
            logger.debug(_("Will blend %s layer(s) into %s") % (len(self._layers),
                                                                tile_abs_uri))
            self.blend_layers(tile_abs_uri, (z, x, y))

        # If taken or rendered in cache, copy it to temporary dir
        if self.cache and self.tmp_dir != self.tiles_dir:
            tmp_dir = os.path.join(self.tmp_dir, tile_dir)
            if not os.path.isdir(tmp_dir):
                os.makedirs(tmp_dir)
            shutil.copy(tile_abs_uri, tmp_dir)

    def blend_layers(self, tile_fullpath, (z, x, y)):
        """
        Merge tiles of all layers into the specified tile path
        """
        # Background first
        background = Image.open(tile_fullpath)
        result = Image.new("RGBA", (self.tile_size, self.tile_size))
        result.paste(background, (0, 0))
        
        for layer in self._layers:
            try:
                # Prepare tile of overlay, if available
                layer.prepare_tile((z, x, y))
            except (DownloadError, ExtractionError), e:
                logger.warn(e)
                continue
            # Extract alpha mask
            tile_over = layer.tile_fullpath((z, x, y))
            overlay = Image.open(tile_over)
            overlay = overlay.convert("RGBA")
            r, g, b, a = overlay.split()
            overlay = Image.merge("RGB", (r, g, b))
            mask = Image.merge("L", (a,))
            result.paste(overlay, (0, 0), mask)
        result.save(tile_fullpath)

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

    @property
    def zoomlevels(self):
        """
        Return the list of covered zoom levels
        """
        return self._bboxes[0][1]  #TODO: merge all coverages

    @property
    def bounds(self):
        """
        Return the bounding box of covered areas
        """
        return self._bboxes[0][0]  #TODO: merge all coverages

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

        # If no coverage added, use bottom layer metadata
        if len(self._bboxes) == 0 and len(self._layers) > 0:
            bottomlayer = self._layers[0]
            metadata = bottomlayer.reader.metadata()
            bbox = map(float, metadata.get('bounds', '').split(','))
            zoomlevels = range(int(metadata.get('minzoom', 0)), int(metadata.get('maxzoom', 0)))
            self.add_coverage(bbox=bbox, zoomlevels=zoomlevels)

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

        # Some metadata
        middlezoom = self.zoomlevels[len(self.zoomlevels)/2]
        lat = self.bounds[1] + (self.bounds[3] - self.bounds[1])/2
        lon = self.bounds[0] + (self.bounds[2] - self.bounds[0])/2
        metadata = {}
        metadata['minzoom'] = self.zoomlevels[0]
        metadata['maxzoom'] = self.zoomlevels[-1]
        metadata['bounds'] = '%s,%s,%s,%s' % tuple(self.bounds)
        metadata['center'] = '%s,%s,%s' % (lon, lat, middlezoom)
        metadatafile = os.path.join(self.tmp_dir, 'metadata.json')
        with open(metadatafile, 'w') as output:
            json.dump(metadata, output)

        # TODO: add UTF-Grid of last layer, if any

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
            for layer in self._layers:
                layer.clean()
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
