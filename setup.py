from setuptools import setup

setup(
    name = 'control',
    version = '0.2',
    description = 'manage processes',
    author = 'Moritz Moeller',
    author_email = 'mm@mxs.de',
    url= 'https://github.com/mo22/control',

    packages = ['control'],
    scripts = ['bin/control'],
    install_requires = [
        'pyyaml',
        'jsonschema',
    ],
)
