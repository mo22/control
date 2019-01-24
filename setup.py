# -*- coding: utf8 -*-
from setuptools import setup
setup(
    name        = 'control',
    packages    = ['control'],
    package_dir = { 'control': '.' },
    scripts     = ['control'],
    version     = '0.1',
    description = 'manage processes',
    author      = 'Moritz Möller',
    author_email= 'mm@mxs.de',
    url         = 'https://github.com/mo22/control',
    install_requires = [
        'pyyaml',
        'jsonschema',
    ],
)

