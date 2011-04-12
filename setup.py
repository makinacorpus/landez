#!/usr/bin/python
# -*- coding: utf8 -*-
from setuptools import setup, find_packages

f = open('README')
readme = f.read()
f.close()

setup(name       = 'landez',
    version      = '0.0',
    license      = 'LGPL',
    description  = 'Build a MBTiles file from a Mapnik stylesheet.',
    author       = "Mathieu Leplatre",
    author_email = "mathieu.leplatre@makina-corpus.com",
    url          = "https://github.com/makinacorpus/landez/",
    download_url = "http://pypi.python.org/pypi/landez/",
    long_description = readme,
    provides     = ['landez'],
    entry_points = dict(
        console_scripts = [
        ]),
    install_requires=[
    ],
    packages     = find_packages(),
    platforms    = ('any',),
    keywords     = ['MBTiles', 'Mapnik'],
    classifiers  = ['Programming Language :: Python :: 2.6',
                    'Operating System :: OS Independent',
                    'Natural Language :: English',
                    'Topic :: Utilities',
                    'Development Status :: 3 - Alpha'],
) 
