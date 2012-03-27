#!/usr/bin/python
# -*- coding: utf8 -*-
import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

setup(
    name='landez',
    version='1.8.2',
    author='Mathieu Leplatre',
    author_email='mathieu.leplatre@makina-corpus.com',
    url='https://github.com/makinacorpus/landez/',
    download_url="http://pypi.python.org/pypi/landez/",
    description="Landez is a python toolbox to manipulate map tiles.",
    long_description=open(os.path.join(here, 'README.rst')).read() + '\n\n' +
                     open(os.path.join(here, 'CHANGES')).read(),
    license='LPGL, see LICENSE file.',
    install_requires=[],
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    keywords=['MBTiles', 'Mapnik'],
    classifiers=['Programming Language :: Python :: 2.6',
                 'Operating System :: OS Independent',
                 'Natural Language :: English',
                 'Topic :: Utilities',
                 'Development Status :: 5 - Production/Stable'],
)
