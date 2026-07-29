from fastapi import FastAPI
from sqlalchemy.engine import Engine

from ocrapi import api

"""The app factory. wtbot embeds this (passing its own shared, already-
migrated engine) rather than talking to a second process; see
wtbot.main.create_app. [engine] must already have wtbot's schema applied
(OcrBackendConfig's table lives there, see wtbot.model.ocr_backend) —
this factory does no migration of its own. For a standalone run against a
real database use ocrapi.dev_server, which builds and migrates one via
wtbot.db:

    uv run fastapi dev src-py/ocrapi/dev_server.py
"""


def create_ocr_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="ocrapi", version="0.1.0")
    app.state.engine = engine
    app.include_router(api.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
