import importlib.metadata
import os

__app_name__ = "wtbot"

# docker is not installing the package, so this is missing
try:
    __version__ = importlib.metadata.version(__app_name__)
except importlib.metadata.PackageNotFoundError:
    # @TODO need to fix the dockerfile for wtbot to install package
    __version__ = "0.1.0"

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
