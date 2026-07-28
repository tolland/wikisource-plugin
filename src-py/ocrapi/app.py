from fastapi import FastAPI
from sqlalchemy.engine import Engine

from ocrapi import api
from ocrapi.db import create_ocr_engine, init_ocr_db

"""The app factory. wtbot embeds this (passing its own shared engine)
rather than talking to a second process; see wtbot.main.create_app. For a
genuinely standalone run — no wtbot, no wiki config, nothing beyond
whatever OCR backends you PUT into ``/config`` — use ocrapi.dev_server,
which is the only place a default on-disk engine gets created:

    uv run fastapi dev src-py/ocrapi/dev_server.py

Deliberately not created at *this* module's import time: wtbot imports
just ``create_ocr_app`` from here, and a module-level ``app = ...`` would
create a default sqlite file as a side effect of that import alone.
"""


def create_ocr_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="ocrapi", version="0.1.0")
    app.state.engine = engine or create_ocr_engine()
    init_ocr_db(app.state.engine)
    app.include_router(api.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
