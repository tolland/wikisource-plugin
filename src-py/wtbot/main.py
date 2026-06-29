"""wtbot FastAPI application.

This is the plugin-facing contract: a thin FastAPI app over the SQLite cache.
Surfaces (VFS, cache-fill, commit) are described in ``src-py/DESIGN.md``; only a
health check and a sites vertical slice are wired up so far.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from wtbot.api import fetch, health, sites, vfs
from wtbot.db import create_db_engine, init_db
from wtbot.worker import ClientFactory, make_client_for_site


def create_app(
    engine: Engine | None = None,
    client_factory: ClientFactory | None = None,
    blob_root: Path | str | None = None,
) -> FastAPI:
    """Build the app. Pass an ``engine`` to point at a different database, a
    ``client_factory`` to inject a fake wiki client, and a ``blob_root`` for
    the file-blob download cache (all three are used by tests)."""
    engine = engine or create_db_engine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(title="wtbot", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.client_factory = client_factory or make_client_for_site
    app.state.blob_root = (
        Path(blob_root)
        if blob_root is not None
        else Path(os.environ.get("WTBOT_BLOB_ROOT", "./blobs"))
    )

    app.include_router(health.router)
    app.include_router(sites.router)
    app.include_router(fetch.router)
    app.include_router(vfs.router)
    return app


app = create_app()
