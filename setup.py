from setuptools import setup

# package_dir={'': 'src'},
# packages=find_packages('src'),
# __init__.py


setup(
    name         = 'control',
    packages     = ['control'],
    #package_dir  = { 'control': '.' },
    #scripts      = ['control'],
    version      = '0.2',
    description  = 'manage processes',
    author       = 'Moritz Moeller',
    author_email = 'mm@mxs.de',
    url          = 'https://github.com/mo22/control',
    #zip_safe     = False,
    install_requires = [
        'pyyaml',
        'jsonschema',
    ],
)
