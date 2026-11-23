from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('fafafa-famugong')
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = ''
