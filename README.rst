*Landez* manipulates tiles, builds MBTiles and arrange tiles together into single images.

Tiles can either be obtained from a remote tile service URL, from a local Mapnik stylesheet
or from MBTiles files.

For building MBTiles, it uses *mbutil* from Mapbox https://github.com/mapbox/mbutil at the final stage.
The land covered is specified using a list of bounding boxes and zoom levels.


=======
INSTALL
=======

*Landez* requires nothing but python remote mode (specifying a tiles URL), but 
requires `mapnik` if the tiles are drawn locally. ::

    sudo aptitude install python-mapnik

And `PIL` to export arranged tiles into images. ::

    sudo aptitude install python-imaging


=====
USAGE
=====

Building MBTiles files
======================

Remote tiles
------------

Using a remote tile service (Cloudmade by default):
::

    import logging
    from landez import MBTilesBuilder

    logging.basicConfig(level=logging.DEBUG)
        
    mb = MBTilesBuilder(remote=True, cache=False)
    mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), 
                        zoomlevels=[0, 1])
    mb.run()

Please respect `Tile usage policies <http://wiki.openstreetmap.org/wiki/Tile_usage_policy>`

Local rendering
---------------

Using mapnik to render tiles:
::

    import logging
    from landez import MBTilesBuilder
    
    logging.basicConfig(level=logging.DEBUG)
    
    mb = MBTilesBuilder(stylefile="yourstyle.xml", filepath="dest.mbtiles")
    mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), 
                    zoomlevels=[0, 1])
    mb.run()


From an other MBTiles file
--------------------------
::

    import logging
    from landez import MBTilesBuilder
    
    logging.basicConfig(level=logging.DEBUG)
    
    mb = MBTilesBuilder(mbtiles_file="yourfile.mbtiles", filepath="dest.mbtiles")
    mb.add_coverage(bbox=(-180.0, -90.0, 180.0, 90.0), 
                    zoomlevels=[0, 1])
    mb.run()


Manipulate tiles
================

::

    from landez import MBTilesBuilder
    
    # From a TMS tile server
    # tm = TilesManager(tiles_url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")
    
    # From a MBTiles file
    tm = TilesManager(mbtiles_file="yourfile.mbtiles")
    
    tiles = tm.tileslist(bbox=(-180.0, -90.0, 180.0, 90.0), 
                         zoomlevels=[0, 1])
    for tile in tiles:
        tm.prepare_tile(tile)  # download, extract or take from cache
        tile_path = tm.tile_fullpath(tile)
        ...


Export Images
=============

Specify tiles sources in the exact same way as for building MBTiles files.

::

    import logging
    from landez import ImageExporter
    
    logging.basicConfig(level=logging.DEBUG)
    
    ie = ImageExporter(mbtiles_file="yourfile.mbtiles")
    ie.export_image(bbox=(-180.0, -90.0, 180.0, 90.0), zoomlevel=3, imagepath="image.png")


=======
AUTHORS
=======

    * Mathieu Leplatre <mathieu.leplatre@makina-corpus.com>
    * Sergej Tatarincev
    * Thanks to mbutil authors <https://github.com/mapbox/mbutil>

=======
LICENSE
=======

    * Lesser GNU Public License
