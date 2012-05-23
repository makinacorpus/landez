import os
import re
import logging
import shutil
from gettext import gettext as _

logger = logging.getLogger(__name__)


class Cache(object):
    def __init__(self, basename, folder):
        self._basename = None
        self.folder = folder
        self.basename = basename

    @property
    def basename(self):
        return self._basename
    
    @basename.setter
    def basename(self, basename):
        self._basename = basename
        subfolder = re.sub(r'[^a-z^A-Z^0-9]+', '', basename)
        self.folder = os.path.join(self.folder, subfolder)

    @classmethod
    def tile_file(cls, (z, x, y)):
        tile_dir = os.path.join("%s" % z, "%s" % x)
        y_mercator = (2**z - 1) - y
        tile_name = "%s.png" % y_mercator
        return tile_dir, tile_name
    
    def tile_fullpath(self, (z, x, y)):
        tile_dir, tile_name = self.tile_file((z, x, y))
        tile_abs_dir = os.path.join(self.folder, tile_dir)
        return os.path.join(tile_abs_dir, tile_name)

    def read(self, (z, x, y)):
        raise NotImplementedError

    def save(self, body, (z, x, y)):
        raise NotImplementedError

    def remove(self, (z, x, y)):
        tile_abs_uri = self.tile_fullpath((z, x, y))
        os.remove(tile_abs_uri)
        parent = os.path.dirname(tile_abs_uri)
        i = 0
        while i <= 3:  # try to remove 3 levels (cache/z/x/)
            try:
                os.rmdir(parent)
                parent = os.path.dirname(parent)
                i += 1
            except OSError:
                break

    def clean(self):
        raise NotImplementedError


class Disk(Cache):
    def read(self, (z, x, y)):
        tile_abs_uri = self.tile_fullpath((z, x, y))
        if os.path.exists(tile_abs_uri):
            logger.debug(_("Found %s") % tile_abs_uri)
            return open(tile_abs_uri, 'r').read()
        return None

    def save(self, body, (z, x, y)):
        tile_abs_uri = self.tile_fullpath((z, x, y))
        tile_abs_dir = os.path.dirname(tile_abs_uri)
        if not os.path.isdir(tile_abs_dir):
            os.makedirs(tile_abs_dir)
        logger.debug(_("Save %s bytes to %s") % (len(body), tile_abs_uri))
        open(tile_abs_uri, 'wb').write(body)

    def clean(self):
        pass


class Temporary(Disk):
    def clean(self):
        logger.debug(_("Clean-up %s") % self.folder)
        try:
            shutil.rmtree(self.folder)
        except OSError:
            logger.warn(_("%s was missing.") % self.folder)
