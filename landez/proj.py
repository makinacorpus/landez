from math import pi, cos, sin, log, exp, atan, tan

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi
MAX_LATITUDE = 85.0511287798
EARTH_RADIUS = 6378137


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

    def tile_at(self, zoom, position):
        """
        Returns a tuple of (z, x, y) 
        """
        x, y = self.fromLLtoPixel(position, zoom)
        return (zoom, int(x/self.tilesize), int(y/self.tilesize))

    def tile_bbox(self, (z, x, y)):
        """
        Returns the WGS84 bbox of the specified tile
        """
        topleft = (x * self.tilesize, (y + 1) * self.tilesize)
        bottomright = ((x + 1) * self.tilesize, y * self.tilesize)
        nw = self.fromPixelToLL(topleft, z)
        se = self.fromPixelToLL(bottomright, z)
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
