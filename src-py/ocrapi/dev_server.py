import os

from ocrapi.app import create_ocr_app
from wtbot.db import create_db_engine, init_db

"""Standalone dev entry point: `uv run fastapi dev src-py/ocrapi/dev_server.py`.
OcrBackendConfig is wtbot's own app state (see wtbot.model.ocr_backend), so
running this still needs wtbot's schema -- this builds and migrates a
throwaway `database.db` in the working directory via wtbot.db, the same
engine wtbot itself would build. Point WTBOT_DB_URL at a real one (e.g.
wtbot's own database.db) to configure backends against the same rows the
plugin sees."""

_engine = create_db_engine(os.environ.get("WTBOT_DB_URL", "sqlite:///database.db"))
init_db(_engine)

app = create_ocr_app(_engine)
