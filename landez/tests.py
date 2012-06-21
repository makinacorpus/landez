import os
import logging
import unittest

from tiles import (TilesManager, MBTilesBuilder, ImageExporter,
                   EmptyCoverageError, DownloadError)
from proj import InvalidCoverageError
from cache import Disk
from sources import MBTilesReader


class TestTilesManager(unittest.TestCase):
    def test_format(self):
        mb = TilesManager()
        self.assertEqual(mb.tile_format, 'image/png')
        self.assertEqual(mb.cache.extension, '.png')
        # Format from WMS options
        mb = TilesManager(wms_server='dumb', wms_layers=['dumber'],
                          wms_options={'format': 'image/jpeg'})
        self.assertEqual(mb.tile_format, 'image/jpeg')
        self.assertEqual(mb.cache.extension, '.jpeg')
        # Format from URL extension
        mb = TilesManager(tiles_url='http://tileserver/{z}/{x}/{y}.jpg')
        self.assertEqual(mb.tile_format, 'image/jpeg')
        self.assertEqual(mb.cache.extension, '.jpeg')
        mb = TilesManager(tiles_url='http://tileserver/{z}/{x}/{y}.png')
        self.assertEqual(mb.tile_format, 'image/png')
        self.assertEqual(mb.cache.extension, '.png')
        # No extension in URL
        mb = TilesManager(tiles_url='http://tileserver/tiles/')
        self.assertEqual(mb.tile_format, 'image/png')
        self.assertEqual(mb.cache.extension, '.png')
        mb = TilesManager(tile_format='image/gif',
                          tiles_url='http://tileserver/tiles/')
        self.assertEqual(mb.tile_format, 'image/gif')
        self.assertEqual(mb.cache.extension, '.gif')

    def test_tileslist(self):
        mb = TilesManager()
        # World at level 0
        l = mb.tileslist((-180.0, -90.0, 180.0, 90.0), [0])
        self.assertEqual(l, [(0, 0, 0)])
        # World at levels [0, 1]
        l = mb.tileslist((-180.0, -90.0, 180.0, 90.0), [0, 1])
        self.assertEqual(l, [(0, 0, 0),
                             (1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 1, 1)])
        # Incorrect bounds
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-90.0, -180.0, 180.0, 90.0), [])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0, 180.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0, 181.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-90.0, 180.0, 180.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-30.0, -90.0, -50.0, 90.0), [0])

    def test_download_tile(self):
        mb = TilesManager(cache=False)
        tile = (1, 1, 1)
        # Unknown URL keyword
        mb = TilesManager(tiles_url="http://{X}.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.assertRaises(DownloadError, mb.tile, (1, 1, 1))
        # With subdomain keyword
        mb = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")
        content = mb.tile(tile)
        self.assertTrue(content is not None)
        # No subdomain keyword
        mb = TilesManager(tiles_url="http://tile.cloudmade.com/f1fe9c2761a15118800b210c0eda823c/1/{size}/{z}/{x}/{y}.png")
        content = mb.tile(tile)
        self.assertTrue(content is not None)
        # Subdomain in available range
        mb = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                          tiles_subdomains=list("abc"))
        for y in range(3):
            content = mb.tile((10, 0, y))
            self.assertTrue(content is not None)
        # Subdomain out of range
        mb = TilesManager(tiles_subdomains=list("abcz"))
        self.assertRaises(DownloadError, mb.tile, (10, 1, 2))
        # Invalid URL
        mb = TilesManager(tiles_url="http://{s}.osm.com")
        self.assertRaises(DownloadError, mb.tile, (10, 1, 2))


class TestMBTilesBuilder(unittest.TestCase):
    def test_init(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.filepath, os.path.join(os.getcwd(), 'tiles.mbtiles'))
        self.assertEqual(mb.cache.folder, '/tmp/landez/stileopenstreetmaporg')
        self.assertEqual(mb.tmp_dir, '/tmp/landez/tiles')

        mb = MBTilesBuilder(filepath='/foo/bar/toto.mb')
        self.assertEqual(mb.cache.folder, '/tmp/landez/stileopenstreetmaporg')
        self.assertEqual(mb.tmp_dir, '/tmp/landez/toto')

    def test_run(self):
        mb = MBTilesBuilder(filepath='big.mbtiles')
        # Fails if no coverage
        self.assertRaises(EmptyCoverageError, mb.run, True)
        # Runs well from web tiles
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[0, 1])
        mb.run(force=True)
        self.assertEqual(mb.nbtiles, 5)
        # Read from other mbtiles
        mb2 = MBTilesBuilder(filepath='small.mbtiles', mbtiles_file=mb.filepath, cache=False)
        mb2.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[1])
        mb2.run(force=True)
        self.assertEqual(mb2.nbtiles, 4)
        os.remove('small.mbtiles')
        os.remove('big.mbtiles')

    def test_run_jpeg(self):
        output = 'mq.mbtiles'
        mb = MBTilesBuilder(filepath=output, 
                            tiles_url='http://oatile1.mqcdn.com/tiles/1.0.0/sat/{z}/{x}/{y}.jpg')
        mb.add_coverage(bbox=(1.3, 43.5, 1.6, 43.7), zoomlevels=[10])
        mb.run(force=True)
        self.assertEqual(mb.nbtiles, 4)
        # Check result
        reader = MBTilesReader(output)
        self.assertEqual(reader.metadata().get('format'), 'jpeg')
        os.remove(output)

    def test_clean_gather(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.tmp_dir, '/tmp/landez/tiles')
        self.assertFalse(os.path.exists(mb.tmp_dir))
        mb._gather((1, 1, 1))
        self.assertTrue(os.path.exists(mb.tmp_dir))
        mb._clean_gather()
        self.assertFalse(os.path.exists(mb.tmp_dir))


class TestImageExporter(unittest.TestCase):
    def test_gridtiles(self):
        mb = ImageExporter()
        # At zoom level 0
        grid = mb.grid_tiles((-180.0, -90.0, 180.0, 90.0), 0)
        self.assertEqual(grid, [[(0, 0)]])
        # At zoom level 1
        grid = mb.grid_tiles((-180.0, -90.0, 180.0, 90.0), 1)
        self.assertEqual(grid, [[(0, 0), (1, 0)],
                                [(0, 1), (1, 1)]])

    def test_exportimage(self):
        from PIL import Image
        output = "image.png"
        ie = ImageExporter()
        ie.export_image((-180.0, -90.0, 180.0, 90.0), 2, output)
        i = Image.open(output)
        self.assertEqual((1024, 1024), i.size)
        os.remove(output)
        # Test from other mbtiles
        mb = MBTilesBuilder(filepath='toulouse.mbtiles')
        mb.add_coverage(bbox=(1.3, 43.5, 1.6, 43.7), zoomlevels=[12])
        mb.run()
        ie = ImageExporter(mbtiles_file=mb.filepath)
        ie.export_image((1.3, 43.5, 1.6, 43.7), 12, output)
        os.remove('toulouse.mbtiles')
        i = Image.open(output)
        self.assertEqual((1280, 1024), i.size)
        os.remove(output)


class TestCache(unittest.TestCase):

    def test_folder(self):
        c = Disk('foo', '/tmp/')
        self.assertEqual(c.folder, '/tmp/foo')
        c.basename = 'bar'
        self.assertEqual(c.folder, '/tmp/bar')

    def test_clean(self):
        mb = TilesManager()
        self.assertEqual(mb.cache.folder, '/tmp/landez/stileopenstreetmaporg')
        # Missing dir
        self.assertFalse(os.path.exists(mb.cache.folder))
        mb.cache.clean()
        # Empty dir
        os.makedirs(mb.cache.folder)
        self.assertTrue(os.path.exists(mb.cache.folder))
        mb.cache.clean()
        self.assertFalse(os.path.exists(mb.cache.folder))


class TestLayers(unittest.TestCase):
    def test_cache_folder(self):
        mb = TilesManager(tiles_url='http://server')
        self.assertEqual(mb.cache.folder, '/tmp/landez/server')
        over = TilesManager(tiles_url='http://toto')
        self.assertEqual(over.cache.folder, '/tmp/landez/toto')
        mb.add_layer(over)
        self.assertEqual(mb.cache.folder, '/tmp/landez/servertoto10')
        mb.add_layer(over, 0.5)
        self.assertEqual(mb.cache.folder, '/tmp/landez/servertoto10toto05')


class TestFilters(unittest.TestCase):
    def test_cache_folder(self):
        from filters import ColorToAlpha
        mb = TilesManager(tiles_url='http://server')
        self.assertEqual(mb.cache.folder, '/tmp/landez/server')
        mb.add_filter(ColorToAlpha('#ffffff'))
        self.assertEqual(mb.cache.folder, '/tmp/landez/servercolortoalphaffffff')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
