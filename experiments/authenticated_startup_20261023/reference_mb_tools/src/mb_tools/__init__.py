from importlib.metadata import version as _dist_version

__version__ = _dist_version("mb-tools")

__all__ = ["__version__"]