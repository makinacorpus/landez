import os
import logging
import mock
import unittest
import shutil
import tempfile
import json
import sqlite3

from .tiles import (TilesManager, MBTilesBuilder, ImageExporter,
                   EmptyCoverageError, DownloadError)
from .proj import InvalidCoverageError
from .cache import Disk
from .sources import MBTilesReader


class TestTilesManager(unittest.TestCase):
    def test_format(self):
        mb = TilesManager()
        self.assertEqual(mb.tile_format, 'image/png')
        self.assertEqual(mb.cache.extension, '.png')
        # Format from WMS options
        mb = TilesManager(wms_server='dumb', wms_layers=['dumber'],
                          wms_options={'format': 'image/jpeg'})

        self.assertEqual(mb.tile_format, 'image/jpeg')
        self.assertTrue(mb.cache.extension, '.jpeg')
        # Format from URL extension
        mb = TilesManager(tiles_url='http://tileserver/{z}/{x}/{y}.jpg')
        self.assertEqual(mb.tile_format, 'image/jpeg')
        self.assertTrue(mb.cache.extension, '.jpeg')
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

    def test_tileslist_at_z1_x0_y0(self):
        mb = TilesManager()
        l = mb.tileslist((-180.0, 1, -1, 90.0), [1])
        self.assertEqual(l, [(1, 0, 0)])

    def test_tileslist_at_z1_x0_y0_tms(self):
        mb = TilesManager(tile_scheme='tms')
        l = mb.tileslist((-180.0, 1, -1, 90.0), [1])

        self.assertEqual(l, [(1, 0, 1)])

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
        mb = TilesManager(tiles_url="http://tile.openstreetmap.org/{z}/{x}/{y}.png")
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
    temp_cache = os.path.join(tempfile.gettempdir(), 'landez/stileopenstreetmaporg_z_x_ypng')
    temp_dir = os.path.join(tempfile.gettempdir(), 'landez/tiles')

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_cache)
        except OSError:
            pass
        try:
            shutil.rmtree(self.temp_dir)
        except OSError:
            pass
        try:
            os.remove('tiles.mbtiles')
        except OSError:
            pass

    def test_init(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.filepath, os.path.join(os.getcwd(), 'tiles.mbtiles'))
        self.assertEqual(mb.cache.folder, self.temp_cache)
        self.assertEqual(mb.tmp_dir, self.temp_dir)

        mb = MBTilesBuilder(filepath='/foo/bar/toto.mb')
        self.assertEqual(mb.cache.folder, self.temp_cache)
        self.assertEqual(mb.tmp_dir, os.path.join(tempfile.gettempdir(), 'landez/toto'))

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
        mb2.add_coverage(bbox=(-180.0, 1, -1, 90.0), zoomlevels=[1])
        mb2.run(force=True)
        self.assertEqual(mb2.nbtiles, 1)
        os.remove('small.mbtiles')
        os.remove('big.mbtiles')

    def test_run_with_errors(self):
        if os.path.exists('tiles.mbtiles'):
            os.remove('tiles.mbtiles')
        mb = MBTilesBuilder(tiles_url='http://foo.bar')
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[0, 1])
        self.assertRaises(DownloadError, mb.run)
        mb = MBTilesBuilder(tiles_url='http://foo.bar', ignore_errors=True)
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[0, 1])
        mb.run()

    @mock.patch('requests.get')
    def test_run_jpeg(self, mock_get):
        mock_get.return_value.content = b'jpeg'
        mock_get.return_value.status_code = 200
        output = 'mq.mbtiles'
        mb = MBTilesBuilder(filepath=output,
                            tiles_url='https://proxy-ign.openstreetmap.fr/94GjiyqD/bdortho/{z}/{x}/{y}.jpg')
        mb.add_coverage(bbox=(1.3, 43.5, 1.6, 43.7), zoomlevels=[10])
        mb.run(force=True)
        self.assertEqual(mb.nbtiles, 4)
        # Check result
        reader = MBTilesReader(output)
        self.assertTrue(reader.metadata().get('format'),  'jpeg')
        os.remove(output)

    def test_clean_gather(self):
        mb = MBTilesBuilder()
        mb._clean_gather()
        self.assertEqual(mb.tmp_dir, self.temp_dir)
        self.assertFalse(os.path.exists(mb.tmp_dir))
        mb._gather((1, 1, 1))
        self.assertTrue(os.path.exists(mb.tmp_dir))
        mb._clean_gather()
        self.assertFalse(os.path.exists(mb.tmp_dir))

    def test_grid_content(self):
        here = os.path.abspath(os.path.dirname(__file__))
        mb = MBTilesBuilder(
            stylefile=os.path.join(here, "data_test", "stylesheet.xml"),
            grid_fields=["NAME"],
            grid_layer=0,
            filepath='foo.mbtiles',
            cache=False
        )

        mb.add_coverage(bbox=(-180, -90, 180, 90), zoomlevels=[2])
        mb.run()

        mbtiles_path = os.path.join(os.getcwd(), 'foo.mbtiles')
        mbtiles = sqlite3.connect(mbtiles_path).cursor()
        grid = mbtiles.execute("SELECT grid FROM grids WHERE zoom_level=2 AND tile_column=1 AND tile_row=1")
        produced_data = json.loads(mb.grid((2, 1, 1)))['data']['39']['NAME']
        expected_data = 'Costa Rica'
        os.remove('foo.mbtiles')
        self.assertEqual(produced_data, expected_data)

    def test_zoomlevels(self):
        mb = MBTilesBuilder()
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[0, 1])
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[11, 12])
        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[5])
        self.assertEqual(mb.zoomlevels[0], 0)
        self.assertEqual(mb.zoomlevels[1], 1)
        self.assertEqual(mb.zoomlevels[2], 5)
        self.assertEqual(mb.zoomlevels[3], 11)
        self.assertEqual(mb.zoomlevels[4], 12)


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
    temp_path = os.path.join(tempfile.gettempdir(), 'landez/stileopenstreetmaporg_z_x_ypng')

    def clean(self):
        try:
            shutil.rmtree(self.temp_path)
        except OSError:
            pass

    def test_folder(self):
        c = Disk('foo', '/tmp/')
        self.assertEqual(c.folder, '/tmp/foo')
        c.basename = 'bar'
        self.assertEqual(c.folder, '/tmp/bar')

    def test_remove(self):
        mb = TilesManager()
        mb.cache.save(b'toto', (1, 1, 1))
        self.assertTrue(os.path.exists('/tmp/landez/stileopenstreetmaporg_z_x_ypng/1/1/0.png'))
        mb.cache.remove((1, 1, 1))
        self.assertFalse(os.path.exists('/tmp/landez/stileopenstreetmaporg_z_x_ypng/1/1/0.png'))
        mb.cache.clean()
        self.assertFalse(os.path.exists(mb.cache.folder))

    def test_clean(self):
        mb = TilesManager()
        self.assertEqual(mb.cache.folder, self.temp_path)
        # Missing dir
        self.assertFalse(os.path.exists(mb.cache.folder))
        mb.cache.clean()
        # Empty dir
        os.makedirs(mb.cache.folder)
        self.assertTrue(os.path.exists(mb.cache.folder))
        mb.cache.clean()
        self.assertFalse(os.path.exists(mb.cache.folder))

    def test_cache_scheme_WMTS(self):
        tm = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", cache=True, cache_scheme='wmts')
        self.assertEqual(tm.cache.scheme, 'xyz')

    def test_cache_with_bad_scheme(self):
        with self.assertRaises(AssertionError):
            TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", cache=True, cache_scheme='badscheme')

    def test_cache_is_stored_at_WMTS_format(self):
        tm = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", cache=True, cache_scheme='wmts')
        tilecontent = tm.tile((12, 2064, 1495))
        self.assertTrue(os.path.exists(os.path.join(self.temp_path, '12', '2064', '1495.png')))

    def test_cache_is_stored_at_TMS_format(self):
        tm = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", cache=True, cache_scheme='tms')
        tilecontent = tm.tile((12, 2064, 1495))
        self.assertTrue(os.path.exists(os.path.join(self.temp_path, '12', '2064', '2600.png')))

    def setUp(self):
        self.clean()

    def tearDown(self):
        self.clean()


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
        from .filters import ColorToAlpha
        mb = TilesManager(tiles_url='http://server')
        self.assertEqual(mb.cache.folder, '/tmp/landez/server')
        mb.add_filter(ColorToAlpha('#ffffff'))
        self.assertEqual(mb.cache.folder, '/tmp/landez/servercolortoalphaffffff')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
