import zlib
import sqlite3
import logging
import json
from gettext import gettext as _
from pkg_resources import parse_version
import urllib

from . import DEFAULT_TILE_SIZE
from proj import GoogleProjection


logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """ Raised when extraction of tiles from specified MBTiles has failed """
    pass

class InvalidFormatError(Exception):
    """ Raised when reading of MBTiles content has failed """
    pass


class Reader(object):
    def __init__(self, tilesize=None):
        if not tilesize:
            tilesize = DEFAULT_TILE_SIZE
        self.tilesize = tilesize


class MBTilesReader(Reader):
    def __init__(self, filename, tilesize=None):
        super(MBTilesReader, self).__init__(tilesize)
        self.filename = filename
        self._con = None
        self._cur = None

    def _query(self, sql, *args):
        """ Executes the specified `sql` query and returns the cursor """
        if not self._con:
            logger.debug(_("Open MBTiles file '%s'") % self.filename)
            self._con = sqlite3.connect(self.filename)
            self._cur = self._con.cursor()
        sql = ' '.join(sql.split())
        logger.debug(_("Execute query '%s' %s") % (sql, args))
        try:
            self._cur.execute(sql, *args)
        except (sqlite3.OperationalError, sqlite3.DatabaseError), e:
            raise InvalidFormatError(_("%s while reading %s") % (e, self.filename))
        return self._cur

    def metadata(self):
        rows = self._query('SELECT name, value FROM metadata')
        rows = [(row[0], row[1]) for row in rows]
        return dict(rows)

    def zoomlevels(self):
        rows = self._query('SELECT DISTINCT(zoom_level) FROM tiles ORDER BY zoom_level')
        return [int(row[0]) for row in rows]

    def tile(self, z, x, y):
        y_mercator = (2**int(z) - 1) - int(y)
        rows = self._query('''SELECT tile_data FROM tiles 
                              WHERE zoom_level=? AND tile_column=? AND tile_row=?;''', (z, x, y_mercator))
        t = rows.fetchone()
        if not t:
            raise ExtractionError(_("Could not extract tile %s from %s") % ((z, x, y), self.filename))
        return t[0]

    def grid(self, z, x, y, callback=None):
        if not callback:
            callback = 'grid'

        y_mercator = (2**int(z) - 1) - int(y)
        rows = self._query('''SELECT grid FROM grids 
                              WHERE zoom_level=? AND tile_column=? AND tile_row=?;''', (z, x, y_mercator))
        t = rows.fetchone()
        if not t:
            raise ExtractionError(_("Could not extract grid %s from %s") % ((z, x, y), self.filename))
        grid_json = json.loads(zlib.decompress(t[0]))
        
        rows = self._query('''SELECT key_name, key_json FROM grid_data
                              WHERE zoom_level=? AND tile_column=? AND tile_row=?;''', (z, x, y_mercator))
        # join up with the grid 'data' which is in pieces when stored in mbtiles file
        grid_json['data'] = {}
        grid_data = rows.fetchone()
        while grid_data:
            grid_json['data'][grid_data[0]] = json.loads(grid_data[1])
            grid_data = rows.fetchone()
        return '%s(%s);' % (callback, json.dumps(grid_json))

    def find_coverage(self, zoom):
        """
        Returns the bounding box (minx, miny, maxx, maxy) of an adjacent 
        group of tiles at this zoom level.
        """
        # Find a group of adjacent available tiles at this zoom level
        rows = self._query('''SELECT tile_column, tile_row FROM tiles 
                              WHERE zoom_level=? 
                              ORDER BY tile_column, tile_row;''', (zoom,))
        t = rows.fetchone()
        xmin, ymin = t
        previous = t
        while t and t[0] - previous[0] <= 1:
            # adjacent, go on
            previous = t
            t = rows.fetchone()
        xmax, ymax = previous
        # Transform (xmin, ymin) (xmax, ymax) to pixels
        S = self.tilesize
        bottomleft = (xmin * S, (ymax + 1) * S)
        topright = ((xmax + 1) * S, ymin * S)
        # Convert center to (lon, lat)
        proj = GoogleProjection(S, [zoom])  # WGS84
        return proj.fromPixelToLL(bottomleft, zoom) + proj.fromPixelToLL(topright, zoom)


class WMSReader(Reader):
    
    PROJECTION = 'EPSG:3857'
    
    def __init__(self, url, layers, tilesize=None, **kwargs):
        super(WMSReader, self).__init__(tilesize)
        self.url = url
        self.wmsParams = dict(
            service='WMS',
            request='GetMap',
            version='1.1.1',
            styles='',
            format='image/jpeg',
            transparent=False,
            layers=','.join(layers),
            width=self.tilesize,
            height=self.tilesize,
        )
        self.wmsParams.update(**kwargs)
        projectionKey = 'srs'
        if parse_version(self.wmsParams['version']) >= parse_version('1.3'):
            projectionKey = 'crs'
        self.wmsParams[projectionKey] = self.PROJECTION

    def tile(self, z, x, y):
        proj = GoogleProjection(self.tilesize, [z])
        bbox = proj.tile_bbox((z, x, y))
        bbox = proj.project(bbox[:2]) + proj.project(bbox[2:])
        bbox = ','.join(map(str, bbox))
        # Build WMS request URL 
        encodedparams = urllib.urlencode(self.wmsParams)
        url = "%s?%s" % (self.url, encodedparams)
        url += "&bbox=%s" % bbox   # commas are not encoded
        try:
            logger.debug(_("Download '%s'") % url)
            f = urllib.urlopen(url)
            header = f.info().typeheader
            assert header == self.wmsParams['format'], "Invalid WMS response type : %s" % header
            return f.read()
        except (AssertionError, IOError), e:
            raise ExtractionError
