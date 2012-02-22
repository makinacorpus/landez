import os
import tempfile

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


from tiles import *
