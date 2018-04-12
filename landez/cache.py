import os
import re
import logging
import shutil
from gettext import gettext as _
from .util import flip_y

logger = logging.getLogger(__name__)


class Cache(object):
    def __init__(self, **kwargs):
        self.extension = kwargs.get('extension', '.png')
        self._scheme = 'tms'

    def tile_file(self, z_x_y):
        (z, x, y) = z_x_y
        tile_dir = os.path.join("%s" % z, "%s" % x)
        y = flip_y(y, z)
        tile_name = "%s%s" % (y, self.extension)
        return tile_dir, tile_name

    @property
    def scheme(self):
        return self._scheme

    def read(self, z_x_y):
        raise NotImplementedError

    def save(self, body, z_x_y):
        raise NotImplementedError

    def remove(self, z_x_y):
        raise NotImplementedError

    def clean(self):
        raise NotImplementedError


class Dummy(Cache):
    def read(self, z_x_y):
        return None

    def save(self, body, z_x_y):
        pass

    def remove(self, z_x_y):
        pass

    def clean(self):
        pass


class Disk(Cache):
    def __init__(self, basename, folder, **kwargs):
        super(Disk, self).__init__(**kwargs)
        self._basename = None
        self._basefolder = folder
        self.folder = folder
        self.basename = basename

    @property
    def basename(self):
        return self._basename

    @basename.setter
    def basename(self, basename):
        self._basename = basename
        subfolder = re.sub(r'[^a-z^A-Z^0-9^_]+', '', basename.replace("/","_").lower())
        self.folder = os.path.join(self._basefolder, subfolder)

    @Cache.scheme.setter
    def scheme(self, scheme):
        assert scheme in ('wmts', 'xyz', 'tms'), "Unknown scheme %s" % scheme
        self._scheme = 'xyz' if (scheme == 'wmts') else scheme

    def tile_file(self, z_x_y):
        (z, x, y) = z_x_y
        tile_dir = os.path.join("%s" % z, "%s" % x)
        if (self.scheme != 'xyz'):
            y = flip_y(y, z)
        tile_name = "%s%s" % (y, self.extension)
        return tile_dir, tile_name

    def tile_fullpath(self, z_x_y):
        (z, x, y) = z_x_y
        tile_dir, tile_name = self.tile_file((z, x, y))
        tile_abs_dir = os.path.join(self.folder, tile_dir)
        return os.path.join(tile_abs_dir, tile_name)

    def remove(self, z_x_y):
        (z, x, y) = z_x_y
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

    def read(self, z_x_y):
        (z, x, y) = z_x_y
        tile_abs_uri = self.tile_fullpath((z, x, y))
        if os.path.exists(tile_abs_uri):
            logger.debug(_("Found %s") % tile_abs_uri)
            return open(tile_abs_uri, 'rb').read()
        return None

    def save(self, body, z_x_y):
        (z, x, y) = z_x_y
        tile_abs_uri = self.tile_fullpath((z, x, y))
        tile_abs_dir = os.path.dirname(tile_abs_uri)
        if not os.path.isdir(tile_abs_dir):
            os.makedirs(tile_abs_dir)
        logger.debug(_("Save %s bytes to %s") % (len(body), tile_abs_uri))
        open(tile_abs_uri, 'wb').write(body)

    def clean(self):
        logger.debug(_("Clean-up %s") % self.folder)
        try:
            shutil.rmtree(self.folder)
        except OSError:
            logger.warn(_("%s was missing or read-only.") % self.folder)
