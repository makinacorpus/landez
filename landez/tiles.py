import os
import shutil
from math import pi, cos, sin, log, exp, atan
import logging
import tempfile

from mbutil import disk_to_mbtiles
import mapnik


DEFAULT_TILE_SIZE = 256
DEFAULT_TILES_DIR = os.getcwd()
DEFAULT_TMP_DIR = tempfile.gettempdir()
DEFAULT_FILEPATH = os.path.join(DEFAULT_TMP_DIR, "tiles.mbtiles")

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi


logger = logging.getLogger(__name__)


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a


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
        self.maxlevel = max(levels)
        c = tilesize
        for d in levels:
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
    """
    Build a MBTiles file from a Mapnik stylesheet file.
    """
    def __init__(self, stylefile, **kwargs):
        self.stylefile = stylefile
        
        self.filepath = kwargs.get('filepath', DEFAULT_FILEPATH)
        self.basename, ext = os.path.splitext(os.path.basename(self.filepath))
        
        self.tmp_dir = kwargs.get('tmp_dir', DEFAULT_TMP_DIR)
        self.tmp_dir = os.path.join(self.tmp_dir, self.basename)
        self.tiles_dir = kwargs.get('tiles_dir', DEFAULT_TILES_DIR)
        self.tile_size = kwargs.get('tile_size', DEFAULT_TILE_SIZE)
        
        self.proj = GoogleProjection(self.tile_size)
        self._bboxes = []
        self._mapnik = None
        self._prj = None

        # Number of tiles rendered here
        self.rendered = 0

    def add_coverage(bbox, zoomlevels):
        """
        Add a coverage
        """
        self._bboxes.append((bbox, zoomlevels))
        self.zoomlevels = sorted(set(self.zoomlevels + zoomlevels))

    def tileslist(self, bbox, zoomlevels):
        """
        Build the tiles list within the bbox (minx, miny, maxx, maxy) at the specified zoom levels.
        Return a list of tuples (z,x,y)
        """
        if max(zoomlevels) > self.proj.maxlevel:
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

    def run(self):
        """
        Build a MBTile file, only if it does not exist.
        """
        if os.path.exists(self.filepath):
            # Already built, do not do anything.
            logger.info("%s already exists. Do not build it." % self.filepath)
            return 
        
        # Compute list of tiles
        tilelist = []
        for bbox, levels in self._bboxes:
            tilelist.extend(self.tilelist(bbox, levels))
        logger.debug("%s tiles to be packaged." % len(tilelist))

        # Go through whole list of tiles and gather them in tmp_dir
        self.rendered = 0
        for tile in tilelist:
            self.prepare_tile(tile)
        logger.debug("%s tiles rendered." % self.rendered)

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

    def prepare_tile(self, tile):
        """
        Check already rendered tiles in `tiles_dir`, and copy them in the
        same temporary directory.
        """
        x, y, z = tile

        tile_dir = os.path.join("%s" % z, "%s" % x)
        tile_name = "%s.png" % y
        tile_abs_dir = os.path.join(self.tiles_dir, tile_dir)
        tile_abs_uri = os.path.join(tile_abs_dir, tile_name)
        
        # Render missing tiles !
        if not os.path.exists(tile_abs_uri):
            if not os.path.isdir(tile_abs_dir):
                os.makedirs(tile_abs_dir)
            logger.debug("Render tile %s" % os.path.join(tile_dir, tile_name))
            self.render_tile(tile_abs_uri, x, y, z)
            self.rendered += 1
        
        # Copy to temporary dir
        tmp_dir = os.path.join(self.tmp_dir, tile_dir)
        if not os.path.isdir(tmp_dir):
            os.makedirs(tmp_dir)
        shutil.copy(tile_abs_uri, tmp_dir)

    def render_tile(self, tile_uri, x, y, z):
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
        l0 = self._tileprj.fromPixelToLL(p0, z);
        l1 = self._tileprj.fromPixelToLL(p1, z);

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
        im.save(tile_uri, 'png256')
