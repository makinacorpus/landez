import os
import tempfile

""" Default tiles URL """
DEFAULT_TILES_URL = "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
""" Default tiles subdomains """
DEFAULT_TILES_SUBDOMAINS = list("abc")
""" Base temporary folder """
DEFAULT_TMP_DIR = os.path.join(tempfile.gettempdir(), 'landez')
""" Default output MBTiles file """
DEFAULT_FILEPATH = os.path.join(os.getcwd(), "tiles.mbtiles")
""" Default tile size in pixels (*useless* in remote rendering) """
DEFAULT_TILE_SIZE = 256
""" Default tile format (mime-type) """
DEFAULT_TILE_FORMAT = 'image/png'
""" Number of retries for remove tiles downloading """
DOWNLOAD_RETRIES = 3
""" Path to fonts for Mapnik rendering """
TRUETYPE_FONTS_PATH = '/usr/share/fonts/truetype/'

from tiles import *
from sources import *
