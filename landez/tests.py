import os
import logging
import unittest

from tiles import (TilesManager, MBTilesBuilder, ImageExporter, EmptyCoverageError, 
                   InvalidCoverageError, DownloadError)


class TestTilesManager(unittest.TestCase):
    def test_path(self):
        mb = TilesManager()
        self.assertEqual(mb.tmp_dir, '/tmp/landez/stileopenstreetmaporg')
        self.assertEqual(mb.tiles_dir, '/tmp/landez/stileopenstreetmaporg')

    def test_tileslist(self):
        mb = TilesManager()
        
        # World at level 0
        l = mb.tileslist((-180.0, -90.0, 180.0, 90.0), [0])
        self.assertEqual(l, [(0, 0, 0)])
        
        # World at levels [0, 1]
        l = mb.tileslist((-180.0, -90.0, 180.0, 90.0), [0, 1])
        self.assertEqual(l, [(0, 0, 0), 
                             (1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 1, 1)])

        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-90.0, -180.0, 180.0, 90.0), [])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0, 180.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-91.0, -180.0, 181.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-90.0, 180.0, 180.0, 90.0), [0])
        self.assertRaises(InvalidCoverageError, mb.tileslist, (-30.0, -90.0, -50.0, 90.0), [0])

    def test_clean(self):
        mb = TilesManager()
        self.assertEqual(mb.tmp_dir, '/tmp/landez/stileopenstreetmaporg')
        # Missing dir
        self.assertFalse(os.path.exists(mb.tmp_dir))
        mb.clean()
        # Empty dir
        os.makedirs(mb.tmp_dir)
        self.assertTrue(os.path.exists(mb.tmp_dir))
        mb.clean()
        self.assertFalse(os.path.exists(mb.tmp_dir))

    def test_download_tile(self):
        output = '/tmp/tile.png'
        if os.path.exists(output): os.remove(output)
        
        # Unknown URL keyword
        mb = TilesManager()
        mb.tiles_url = "http://{X}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        self.assertRaises(DownloadError, mb.download_tile, output, 1, 1, 1)
        self.assertFalse(os.path.exists(output))
        # With subdomain keyword
        mb.tiles_url = "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        mb.download_tile(output, 1, 1, 1)
        self.assertTrue(os.path.exists(output))
        # No subdomain keyword
        mb.tiles_url = "http://tile.cloudmade.com/f1fe9c2761a15118800b210c0eda823c/1/{size}/{z}/{x}/{y}.png"
        mb.download_tile(output, 1, 1, 1)
        self.assertTrue(os.path.exists(output))
        # Subdomain in available range
        mb.tiles_url = "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        mb.tiles_subdomains = list("abc")
        for y in range(3):
            mb.download_tile(output, 10, 0, y)
            self.assertTrue(os.path.exists(output))
        # Subdomain out of range
        mb.tiles_subdomains = list("abcz")
        self.assertRaises(DownloadError, mb.download_tile, output, 10, 1, 2)
        
        # Clean out
        os.remove(output)


class TestMBTilesBuilder(unittest.TestCase):
    def test_init(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.filepath, os.path.join(os.getcwd(), 'tiles.mbtiles'))
        self.assertEqual(mb.basename, 'tiles')
        self.assertEqual(mb.tmp_dir, '/tmp/landez/stileopenstreetmaporg/tiles')

        mb = MBTilesBuilder(filepath='/foo/bar/toto.mb')
        self.assertEqual(mb.basename, 'toto')
        self.assertEqual(mb.tmp_dir, '/tmp/landez/stileopenstreetmaporg/toto')

    def test_run(self):
        mb = MBTilesBuilder(filepath='big.mbtiles')
        self.assertRaises(EmptyCoverageError, mb.run)

        mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[0, 1])
        mb.run()
        self.assertEqual(mb.nbtiles, 5)

        # Test from other mbtiles
        mb2 = MBTilesBuilder(filepath='small.mbtiles', mbtiles_file=mb.filepath, cache=False)
        mb2.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevels=[1])
        mb2.run()
        self.assertEqual(mb2.nbtiles, 4)
        mb.clean(full=True)
        mb2.clean(full=True)

    def test_clean(self):
        mb = MBTilesBuilder()
        # Missing file
        self.assertEqual(mb.filepath, os.path.join(os.getcwd(), 'tiles.mbtiles'))
        self.assertFalse(os.path.exists(mb.filepath))
        mb.clean()
        # Empty file
        open(mb.filepath, 'w').close() 
        self.assertTrue(os.path.exists(mb.filepath))
        mb.clean()
        self.assertTrue(os.path.exists(mb.filepath))
        mb.clean(full=True)
        self.assertFalse(os.path.exists(mb.filepath))


class TestImageExporter(unittest.TestCase):

    def test_gridtiles(self):
        mb = ImageExporter()

        grid = mb.grid_tiles((-180.0, -90.0, 180.0, 90.0), 0)
        self.assertEqual(grid, [[(0, 0)]])
        
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
        mb.clean(full=True)
        i = Image.open(output)
        self.assertEqual((1280, 1024), i.size)
        os.remove(output)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
