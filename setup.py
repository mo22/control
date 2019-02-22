# -*- coding: utf8 -*-
from setuptools import setup
setup(
    name         = 'control',
    packages     = ['control'],
    package_dir  = { 'control': '.' },
    scripts      = ['control'],
    version      = '0.2',
    description  = 'manage processes',
    author       = 'Moritz Moeller',
    author_email = 'mm@mxs.de',
    url          = 'https://github.com/mo22/control',
    install_requires = [
        'pyyaml',
        'jsonschema',
    ],
)

