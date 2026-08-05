import importlib.metadata
import os

__app_name__ = "wtbot"
__version__ = importlib.metadata.version(__app_name__)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
