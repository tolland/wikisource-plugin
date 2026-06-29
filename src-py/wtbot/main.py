"""wtbot FastAPI application.

This is the plugin-facing contract: a thin FastAPI app over the SQLite cache.
Surfaces (VFS, cache-fill, commit) are described in ``src-py/DESIGN.md``; only a
health check and a sites vertical slice are wired up so far.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from wtbot.api import health, sites
from wtbot.db import create_db_engine, init_db


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the app. Pass an ``engine`` to point at a different database (tests
    use this to run against a throwaway SQLite file)."""
    engine = engine or create_db_engine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(title="wtbot", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine

    app.include_router(health.router)
    app.include_router(sites.router)
    return app


app = create_app()
