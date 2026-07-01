import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from wtbot.api import (
    commit as commit_api,
)
from wtbot.api import (
    edit_journal,
    fetch,
    file_blob,
    health,
    namespace,
    pages,
    sites,
    vfs,
    viewer,
)
from sqlmodel import Session

from wtbot.db import create_db_engine, init_db
from wtbot.settings import WikiSettings
from wtbot.sqlmodel import Site, SiteCredential
from wtbot.worker import ClientFactory
from wtbot.wiki.client import WikiClient, get_wiki_client

"""wtbot FastAPI application.

This is the plugin-facing contract: a thin FastAPI app over the SQLite cache.
Surfaces (VFS, cache-fill, commit) are described in ``src-py/DESIGN.md``; only a
health check and a sites vertical slice are wired up so far.
"""

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
# )


def _make_db_client_factory(engine) -> ClientFactory:
    """Returns a ClientFactory that looks up SiteCredential from the DB
    before falling back to an anonymous WikiSettings. Each call opens its own
    short-lived Session so the factory is safe to call from any thread."""

    def _factory(site: Site) -> WikiClient:
        with Session(engine) as s:
            cred: SiteCredential | None = s.get(SiteCredential, site.pk)
        overrides: dict = {}
        if cred:
            overrides = dict(username=cred.username, password=cred.password, bot_name=cred.bot_name)
        return get_wiki_client(WikiSettings.from_site(site, **overrides))

    return _factory


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
    app.state.client_factory = client_factory or _make_db_client_factory(engine)
    app.state.blob_root = (
        Path(blob_root)
        if blob_root is not None
        else Path(os.environ.get("WTBOT_BLOB_ROOT", "./blobs"))
    )

    app.include_router(commit_api.router)
    app.include_router(edit_journal.router)
    app.include_router(fetch.router)
    app.include_router(file_blob.router)
    app.include_router(health.router)
    app.include_router(namespace.router)
    app.include_router(pages.router)
    app.include_router(sites.router)
    app.include_router(vfs.router)
    app.include_router(viewer.router)

    return app


app = create_app()
