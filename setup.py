#!/usr/bin/python
# -*- coding: utf8 -*-
import os 
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

setup(name       = 'landez',
    version      = '1.8.1',
    license      = 'LGPL',
    description  = 'Landez is a python toolbox to manipulate map tiles.',
    author       = "Mathieu Leplatre",
    author_email = "mathieu.leplatre@makina-corpus.com",
    url          = "https://github.com/makinacorpus/landez/",
    download_url = "http://pypi.python.org/pypi/landez/",
    long_description = open(os.path.join(here, 'README.rst')).read(),
    provides     = ['landez'],
    packages     = find_packages(),
    platforms    = ['any'],
    keywords     = ['MBTiles', 'Mapnik'],
    classifiers  = ['Programming Language :: Python :: 2.6',
                    'Operating System :: OS Independent',
                    'Natural Language :: English',
                    'Topic :: Utilities',
                    'Development Status :: 5 - Production/Stable'],
) 
