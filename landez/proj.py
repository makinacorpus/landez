from math import pi, sin, log, exp, atan, tan
from gettext import gettext as _


DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi
MAX_LATITUDE = 85.0511287798
EARTH_RADIUS = 6378137


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a


class InvalidCoverageError(Exception):
    """ Raised when coverage bounds are invalid """
    pass


class GoogleProjection(object):

    NAME = 'EPSG:3857'

    """
    Transform Lon/Lat to Pixel within tiles
    Originally written by OSM team : http://svn.openstreetmap.org/applications/rendering/mapnik/generate_tiles.py     
    """
    def __init__(self, tilesize, levels = [0]):
        if not levels:
            raise InvalidCoverageError(_("Wrong zoom levels.")) 
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        self.levels = levels
        self.maxlevel = max(levels) + 1
        self.tilesize = tilesize
        c = tilesize
        for d in range(self.maxlevel):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
    
    def project_pixels(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def unproject_pixels(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)

    def tile_at(self, zoom, position):
        """
        Returns a tuple of (z, x, y) 
        """
        x, y = self.project_pixels(position, zoom)
        return (zoom, int(x/self.tilesize), int(y/self.tilesize))

    def tile_bbox(self, (z, x, y)):
        """
        Returns the WGS84 bbox of the specified tile
        """
        topleft = (x * self.tilesize, (y + 1) * self.tilesize)
        bottomright = ((x + 1) * self.tilesize, y * self.tilesize)
        nw = self.unproject_pixels(topleft, z)
        se = self.unproject_pixels(bottomright, z)
        return nw + se

    def project(self, (lng, lat)):
        """
        Returns the coordinates in meters from WGS84
        """
        x = lng * DEG_TO_RAD
        lat = max(min(MAX_LATITUDE, lat), -MAX_LATITUDE)
        y = lat * DEG_TO_RAD
        y = log(tan((pi / 4) + (y / 2)))
        return (x*EARTH_RADIUS, y*EARTH_RADIUS)

    def unproject(self, (x, y)):
        """
        Returns the coordinates from position in meters
        """
        lng = x/EARTH_RADIUS * RAD_TO_DEG
        lat = 2 * atan(exp(y/EARTH_RADIUS)) - pi/2 * RAD_TO_DEG
        return (lng, lat)

    def tileslist(self, bbox):
        if len(bbox) != 4:
            raise InvalidCoverageError(_("Wrong format of bounding box."))
        xmin, ymin, xmax, ymax = bbox
        if abs(xmin) > 180 or abs(xmax) > 180 or \
           abs(ymin) > 90 or abs(ymax) > 90:
            raise InvalidCoverageError(_("Some coordinates exceed [-180,+180], [-90, 90]."))
        
        if xmin >= xmax or ymin >= ymax:
            raise InvalidCoverageError(_("Bounding box format is (xmin, ymin, xmax, ymax)"))

        ll0 = (xmin, ymax)  # left top
        ll1 = (xmax, ymin)  # right bottom

        l = []
        for z in self.levels:
            px0 = self.project_pixels(ll0,z)
            px1 = self.project_pixels(ll1,z)
            
            for x in range(int(px0[0]/self.tilesize),
                           int(px1[0]/self.tilesize)+1):
                if (x < 0) or (x >= 2**z):
                    continue
                for y in range(int(px0[1]/self.tilesize),
                               int(px1[1]/self.tilesize)+1):
                    if (y < 0) or (y >= 2**z):
                        continue
                    l.append((z, x, y))
        return l


class _OSRTransformer(object):
    """ Utility class for converting coordinates based on OSR module """
    def __init__(self, proj_name):
        self.lonlat = osr.SpatialReference()
        self.lonlat.ImportFromProj4('+init=epsg:4326')
        self.proj = osr.SpatialReference()
        self.proj.ImportFromProj4('+init=' + proj_name.lower())
        self.from_ll_ct = osr.CoordinateTransformation(self.lonlat, self.proj)
        self.to_ll_ct = osr.CoordinateTransformation(self.proj, self.lonlat)

    def from_lonlat(self, lon, lat):
        return self.from_ll_ct.TransformPoint(lon, lat)

    def to_lonlat(self, x, y):
        return self.to_ll_ct.TransformPoint(x, y)


class _PyProjTransformer(object):
    """ Utility class for converting coordinates based on PyProj module """
    def __init__(self, proj_name):
        self.lonlat = pyproj.Proj(init='EPSG:4326')
        self.proj = pyproj.Proj(init=proj_name)

    def from_lonlat(self, lon, lat):
        return pyproj.transform(self.lonlat, self.proj, lon, lat)

    def to_lonlat(self, x, y):
        return pyproj.transform(self.proj, self.lonlat, x, y)


class _DumbTransformer(object):
    """
    Fallback class for converting coordinates when no proj module is available
    """
    def from_lonlat(self, lon, lat):
        return lon, lat

    def to_lonlat(self, x, y):
        return x, y


# Use the first projection module available
try:
    import pyproj
    ProjTransformer = _PyProjTransformer
    HAS_PROJ = True
except ImportError:
    try:
        from osgeo import osr
        ProjTransformer = _OSRTransformer
        HAS_PROJ = True
    except ImportError:
        import logging
        logger = logging.getLogger(__name__)
        logger.warn('No projection module can be found')
        ProjTransformer = _DumbTransformer
        HAS_PROJ = False


class CustomTileSet(object):
    """ Tileset with custom zoom levels and projections """

    # NOTE 1:
    # The MBTiles specs limits its scope to the global-mercator TMS profile.
    # Using this class, you will break standard compliance of your MBTiles.
    # Consider adding tileset parameters as metadata to enable overlaying of
    # tiles.

    # NOTE 2:
    # For the moment, the lower left corner of the extent is on tile (0, 0) at
    # every zoom level. The TMS spec mentions an 'origin' parameter which
    # makes possible to center the extent in the grid when the extent is not
    # square. Should we implement this?

    def __init__(self, **kwargs):
        """
        The tileset is defined by:
        * tilesize: the pixel size of a tile (square tiles assumed).
          Default: 256.
        * proj: the coordinate system identifier (will be passed to the
          underlying projection library). Default: 'EPSG:3857'.
        * extent: maximal extent of the tileset expressed in map projection.
          Format: (minx, miny, maxx, maxy). Mandatory.
        * level_number: the number of zoom level to use. Default: 18.
        * max_resolution: the pixel scale at the first zoom level.
          Default value will be computed so that extent fits on 1 tile at
          the first zoom level.
        * resolutions: the pixel scale of each zoom level. If set this will
          override level_number and max_resolution. Default to None.
        """
        # Tile size
        self.tilesize = kwargs.get('tilesize', 256)

        # Coordinate system
        self.proj_name = kwargs.get('proj', 'EPSG:3857')
        self.transformer = ProjTransformer(self.proj_name)

        # Tileset extent
        if 'extent' in kwargs:
            # XXX: should we accept and transform lon/lat extent?
            if len(kwargs['extent']) != 4:
                raise InvalidCoverageError(_("Wrong format of bounding box."))
            if kwargs['extent'][0] >= kwargs['extent'][2] or \
               kwargs['extent'][1] >= kwargs['extent'][3]:
                raise InvalidCoverageError(
                        _("Bounding box format is (xmin, ymin, xmax, ymax)"))
            self.extent = tuple(kwargs['extent'])
        else:
            # XXX: Is it possible to deduce extent automatically from the SRS?
            raise TypeError('Mandatory parameter missing: extent')

        # Determine zoom levels
        if 'resolutions' in kwargs:
            self.resolutions = tuple(kwargs['resolutions'])
        else:
            if 'max_resolution' in kwargs:
                max_res = float(kwargs['max_resolution'])
            else:
                map_size = max(self.extent[2] - self.extent[0],
                                self.extent[3] - self.extent[1])
                max_res = float(map_size) / (self.tilesize)
            level_number = kwargs.get('level_number', 21)
            self.resolutions = tuple([max_res / 2**n
                                      for n in range(level_number)])

    def __eq__(self, other):
        """ Define == operator for TileSet object """
        return self.proj_name == other.proj_name and \
                self.resolutions == other.resolutions and \
                self.tilesize == other.tilesize and \
                self.extent == other.extent

    @property
    def NAME(self):
        """ A label for the map projection of this tileset """
        return self.proj_name

    def project_pixels(self, ll, zoom):
        """ Return the pixel coordinates for the specified lon/lat position """
        coords = self.transformer.from_lonlat(ll[0], ll[1])
        res = self.resolutions[zoom]
        x = int((coords[0] - self.extent[0]) / res)
        y = int((coords[1] - self.extent[1]) / res)
        return (x, y,)

    def unproject_pixels(self, px, zoom):
        """ Return the lon/lat coordinates for the specified pixel position """
        res = self.resolutions[zoom]
        x = (px[0] + 0.5) * res + self.extent[0]
        y = (px[1] + 0.5) * res + self.extent[1]
        coords = self.transformer.to_lonlat(x, y)
        return coords

    def tile_at(self, zoom, position):
        """ Return the tile coordinates for the specified lon/lat position """
        # XXX: Move this method to a BaseTileSet class?
        x, y = self.project_pixels(position, zoom)
        return (zoom, int(x/self.tilesize), int(y/self.tilesize))

    def tile_bbox(self, (z, x, y)):
        """ Return the lon/lat bbox of the specified tile """
        # XXX: Move this method to a BaseTileSet class?
        # NOTE: Return the usual (lower-left, upper-right) instead of the
        # (upper-left, lower-right) of GoogleProjection instances.
        ll_p = (x * self.tilesize, y * self.tilesize)
        ur_p = ((x+1) * self.tilesize - 1, (y+1) * self.tilesize - 1)
        ll_g = self.unproject_pixels(ll_p, z)
        ur_g = self.unproject_pixels(ur_p, z)
        return ll_g + ur_g

    def project(self, (lng, lat)):
        """ Convert coordinates from lon/lat to map projection """
        return self.transformer.from_lonlat(lng, lat)

    def unproject(self, (x, y)):
        """ Convert coordinates from map projection to lon/lat """
        return self.transformer.to_lonlat(lng, lat)

    def tileslist(self, bbox, levels=None):
        """ Return the subset of tiles within the specified lon/lat bbox """
        # XXX: Move this method to a BaseTileSet class?
        # XXX: Could this be a generator?
        if len(bbox) != 4:
            raise InvalidCoverageError(_("Wrong format of bounding box."))
        xmin, ymin, xmax, ymax = bbox
        if abs(xmin) > 180 or abs(xmax) > 180 or \
           abs(ymin) > 90 or abs(ymax) > 90:
            raise InvalidCoverageError(
                    _("Some coordinates exceed [-180,+180], [-90, 90]."))
        if xmin >= xmax or ymin >= ymax:
            raise InvalidCoverageError(
                    _("Bounding box format is (xmin, ymin, xmax, ymax)"))

        l = []
        if levels is None:
            levels = range(len(self.resolutions))
        for z in levels:
            if z < 0 or z >= len(self.resolutions):
                continue
            ll_tile = self.tile_at(z, (xmin, ymin)) # lower left tile
            ur_tile = self.tile_at(z, (xmax, ymax)) # upper right tile

            for x in range(ll_tile[1], ur_tile[1]+1):
                for y in range(ll_tile[2], ur_tile[2]+1):
                    l.append((z, x, y))
        return l
