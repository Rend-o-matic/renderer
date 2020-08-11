try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

config = {
    'description': 'Choirless serverless utility functions',
    'author': 'Matt Hamiltone',
    'url': 'https://github.com/choirless/renderer',
    'download_url': 'https://github.com/choirless/renderer',
    'author_email': 'mh@quernus.co.uk',
    'version': '0.1',
    'install_requires': ['requests', 'paho-mqtt', 'ibm_cos_sdk'],
    'packages': ['choirless_lib'],
    'scripts': [],
    'name': 'choirless_lib'
}

setup(**config)

