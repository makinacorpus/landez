import os
import unittest

from tiles import MBTilesBuilder


class TestMBTilesBuilder(unittest.TestCase):
    def test_path(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.basename, 'tiles')
        self.assertEqual(mb.filepath, os.path.join(os.getcwd(), 'tiles.mbtiles'))
        self.assertEqual(mb.tmp_dir, '/tmp/tiles')
        self.assertEqual(mb.tiles_dir, '/tmp')

        mb = MBTilesBuilder(filepath='/foo/bar/toto.mb')
        self.assertEqual(mb.basename, 'toto')
        self.assertEqual(mb.tmp_dir, '/tmp/toto')

    def test_tileslist(self):
        mb = MBTilesBuilder()
        
        # World at level 0
        l = mb.tileslist((-90.0, -180.0, 180.0, 90.0), [0])
        self.assertEqual(l, [(0, 0, 0)])
        
        # World at levels [0, 1]
        l = mb.tileslist((-90.0, -180.0, 180.0, 90.0), [0, 1])
        self.assertEqual(l, [(0, 0, 0), 
                             (1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 1, 1)])

    def test_clean(self):
        mb = MBTilesBuilder()
        self.assertEqual(mb.tmp_dir, '/tmp/tiles')
        # Missing dir
        self.assertFalse(os.path.exists(mb.tmp_dir))
        mb.clean()
        # Empty dir
        os.makedirs(mb.tmp_dir)
        self.assertTrue(os.path.exists(mb.tmp_dir))
        mb.clean()
        self.assertFalse(os.path.exists(mb.tmp_dir))
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


if __name__ == '__main__':
    unittest.main()
