import os
import shutil
import logging
from gettext import gettext as _
import json
import mimetypes
from StringIO import StringIO

from mbutil import disk_to_mbtiles

from . import (DEFAULT_TILES_URL, DEFAULT_TILES_SUBDOMAINS,
               DEFAULT_TMP_DIR, DEFAULT_FILEPATH, DEFAULT_TILE_SIZE,
               DEFAULT_TILE_FORMAT)
from proj import GoogleProjection
from cache import Disk, Dummy
from sources import (MBTilesReader, TileDownloader, WMSReader,
                     MapnikRenderer, ExtractionError, DownloadError)

has_pil = False
try:
    import Image
    import ImageEnhance
    has_pil = True
except ImportError:
    try:
        from PIL import Image, ImageEnhance
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
        cache -- use a local cache to share tiles between runs (default True)

        tiles_dir -- Local folder containing existing tiles if cache is
                     True, or where temporary tiles will be written otherwise
                     (default DEFAULT_TMP_DIR)

        tiles_url -- remote URL to download tiles (*default DEFAULT_TILES_URL*)
        tiles_headers -- HTTP headers to send (*default empty*)

        stylefile -- mapnik stylesheet file (*to render tiles locally*)

        mbtiles_file -- A MBTiles file providing tiles (*to extract its tiles*)

        wms_server -- A WMS server url (*to request tiles*)
        wms_layers -- The list of layers to be requested
        wms_options -- WMS parameters to be requested (see ``landez.reader.WMSReader``)

        tile_size -- default tile size (default DEFAULT_TILE_SIZE)
        tile_format -- default tile format (default DEFAULT_TILE_FORMAT)
        """
        self.tile_size = kwargs.get('tile_size', DEFAULT_TILE_SIZE)
        self.tile_format = kwargs.get('tile_format', DEFAULT_TILE_FORMAT)

        # Tiles Download
        self.tiles_url = kwargs.get('tiles_url', DEFAULT_TILES_URL)
        self.tiles_subdomains = kwargs.get('tiles_subdomains', DEFAULT_TILES_SUBDOMAINS)
        self.tiles_headers = kwargs.get('tiles_headers')

        # Tiles rendering
        self.stylefile = kwargs.get('stylefile')

        # MBTiles reading
        self.mbtiles_file = kwargs.get('mbtiles_file')

        # WMS requesting
        self.wms_server = kwargs.get('wms_server')
        self.wms_layers = kwargs.get('wms_layers', [])
        self.wms_options = kwargs.get('wms_options', {})

        if self.mbtiles_file:
            self.reader = MBTilesReader(self.mbtiles_file, self.tile_size)
        elif self.wms_server:
            assert self.wms_layers, _("Requires at least one layer (see ``wms_layers`` parameter)")
            self.reader = WMSReader(self.wms_server, self.wms_layers,
                                    self.tile_size, **self.wms_options)
            if 'format' in self.wms_options:
                self.tile_format = self.wms_options['format']
                logger.info(_("Tile format set to %s") % self.tile_format)
        elif self.stylefile:
            self.reader = MapnikRenderer(self.stylefile, self.tile_size)
        else:
            mimetype, encoding = mimetypes.guess_type(self.tiles_url)
            if mimetype and mimetype != self.tile_format:
                self.tile_format = mimetype
                logger.info(_("Tile format set to %s") % self.tile_format)
            self.reader = TileDownloader(self.tiles_url, headers=self.tiles_headers,
                                         subdomains=self.tiles_subdomains, tilesize=self.tile_size)

        # Tile files extensions
        self._tile_extension = mimetypes.guess_extension(self.tile_format, strict=False)
        assert self._tile_extension, _("Unknown format %s") % self.tile_format
        if self._tile_extension == '.jpe':
            self._tile_extension = '.jpeg'

        # Cache
        tiles_dir = kwargs.get('tiles_dir', DEFAULT_TMP_DIR)
        if kwargs.get('cache', True):
            self.cache = Disk(self.reader.basename, tiles_dir, extension=self._tile_extension)
        else:
            self.cache = Dummy(extension=self._tile_extension)

        # Overlays
        self._layers = []
        # Filters
        self._filters = []
        # Number of tiles rendered/downloaded here
        self.rendered = 0

    def tileslist(self, bbox, zoomlevels, tms_scheme=False):
        """
        Build the tiles list within the bottom-left/top-right bounding
        box (minx, miny, maxx, maxy) at the specified zoom levels.
        Return a list of tuples (z,x,y)
        """
        proj = GoogleProjection(self.tile_size, zoomlevels, tms_scheme)
        return proj.tileslist(bbox)

    def add_layer(self, tilemanager, opacity=1.0):
        """
        Add a layer to be blended (alpha-composite) on top of the tile.
        tilemanager -- a `TileManager` instance
        opacity -- transparency factor for compositing
        """
        assert has_pil, _("Cannot blend layers without python PIL")
        assert self.tile_size == tilemanager.tile_size, _("Cannot blend layers whose tile size differs")
        assert 0 <= opacity <= 1, _("Opacity should be between 0.0 (transparent) and 1.0 (opaque)")
        self.cache.basename += '%s%.1f' % (tilemanager.cache.basename, opacity)
        self._layers.append((tilemanager, opacity))

    def add_filter(self, filter_):
        """ Add an image filter for post-processing """
        assert has_pil, _("Cannot add filters without python PIL")
        self.cache.basename += filter_.basename
        self._filters.append(filter_)

    def tile(self, (z, x, y)):
        """
        Return the tile (binary) content of the tile and seed the cache.
        """
        output = self.cache.read((z, x, y))
        if output is None:
            output = self.reader.tile(z, x, y)
            # Blend layers
            if len(self._layers) > 0:
                logger.debug(_("Will blend %s layer(s)") % len(self._layers))
                output = self._blend_layers(output, (z, x, y))
            # Apply filters
            for f in self._filters:
                image = f.process(self._tile_image(output))
                output = self._image_tile(image)
            # Save result to cache
            self.cache.save(output, (z, x, y))
            self.rendered += 1
        return output

    def _blend_layers(self, imagecontent, (z, x, y)):
        """
        Merge tiles of all layers into the specified tile path
        """
        result = self._tile_image(imagecontent)
        # Paste each layer
        for (layer, opacity) in self._layers:
            try:
                # Prepare tile of overlay, if available
                overlay = self._tile_image(layer.tile((z, x, y)))
            except (DownloadError, ExtractionError), e:
                logger.warn(e)
                continue
            # Extract alpha mask
            overlay = overlay.convert("RGBA")
            r, g, b, a = overlay.split()
            overlay = Image.merge("RGB", (r, g, b))
            a = ImageEnhance.Brightness(a).enhance(opacity)
            overlay.putalpha(a)
            mask = Image.merge("L", (a,))
            result.paste(overlay, (0, 0), mask)
        # Read result
        return self._image_tile(result)

    def _tile_image(self, data):
        """
        Tile binary content as PIL Image.
        """
        image = Image.open(StringIO(data))
        return image.convert('RGBA')

    def _image_tile(self, image):
        out = StringIO()
        image.save(out, self._tile_extension[1:])
        return out.getvalue()


class MBTilesBuilder(TilesManager):
    def __init__(self, **kwargs):
        """
        A MBTiles builder for a list of bounding boxes and zoom levels.

        filepath -- output MBTiles file (default DEFAULT_FILEPATH)
        tmp_dir -- temporary folder for gathering tiles (default DEFAULT_TMP_DIR/filepath)
        """
        super(MBTilesBuilder, self).__init__(**kwargs)
        self.filepath = kwargs.get('filepath', DEFAULT_FILEPATH)
        # Gather tiles for mbutil
        basename, ext = os.path.splitext(os.path.basename(self.filepath))
        self.tmp_dir = kwargs.get('tmp_dir', DEFAULT_TMP_DIR)
        self.tmp_dir = os.path.join(self.tmp_dir, basename)
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
        Build a MBTile file.

        force -- overwrite if MBTiles file already exists.
        """
        if os.path.exists(self.filepath):
            if force:
                logger.warn(_("%s already exists. Overwrite.") % self.filepath)
                os.remove(self.filepath)
            else:
                # Already built, do not do anything.
                logger.info(_("%s already exists. Nothing to do.") % self.filepath)
                return

        # Clean previous runs
        self._clean_gather()

        # If no coverage added, use bottom layer metadata
        if len(self._bboxes) == 0 and len(self._layers) > 0:
            bottomlayer = self._layers[0]
            metadata = bottomlayer.reader.metadata()
            if 'bounds' in metadata:
                logger.debug(_("Use bounds of bottom layer %s") % bottomlayer)
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
            self._gather((z, x, y))

        logger.debug(_("%s tiles were missing.") % self.rendered)

        # Some metadata
        middlezoom = self.zoomlevels[len(self.zoomlevels)/2]
        lat = self.bounds[1] + (self.bounds[3] - self.bounds[1])/2
        lon = self.bounds[0] + (self.bounds[2] - self.bounds[0])/2
        metadata = {}
        metadata['format'] = self._tile_extension[1:]
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
        try:
            os.remove("%s-journal" % self.filepath)  # created by mbutil
        except OSError, e:
            logger.debug(e)
        self._clean_gather()

    def _gather(self, (z, x, y)):
        tile_dir, tile_name = self.cache.tile_file((z, x, y))
        tmp_dir = os.path.join(self.tmp_dir, tile_dir)
        if not os.path.isdir(tmp_dir):
            os.makedirs(tmp_dir)
        tilecontent = self.tile((z, x, y))
        with open(os.path.join(tmp_dir, tile_name), 'wb') as f:
            f.write(tilecontent)

    def _clean_gather(self):
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
                img = self._tile_image(self.tile((zoomlevel, x, y)))
                result.paste(img, offset)
        logger.info(_("Save resulting image to '%s'") % imagepath)
        result.save(imagepath)
