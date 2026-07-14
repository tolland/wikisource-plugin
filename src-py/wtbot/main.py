import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from wtbot.api import (
    annotations,
    edit_journal,
    fetch,
    file_blob,
    health,
    namespace,
    page_image,
    page_meta,
    page_nav,
    pages,
    preview,
    sites,
    vfs,
    viewer,
)
from wtbot.api import (
    commit as commit_api,
)
from wtbot.db import create_db_engine, init_db
from wtbot.logging_config import LOGGING_CONFIG, LoggingConfig, configure_logging
from wtbot.logging_config import sqlalchemy_echo as configured_sqlalchemy_echo
from wtbot.model import Site, SiteCredential
from wtbot.settings import WikiSettings
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.worker import ClientFactory

"""wtbot FastAPI application.

This is the plugin-facing contract: a thin FastAPI app over the SQLite cache.
Surfaces (VFS, cache-fill, commit) are described in ``src-py/DESIGN.md``; only a
health check and a sites vertical slice are wired up so far.
"""


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Custom title",
        version="2.5.0",
        summary="This is a very custom OpenAPI schema",
        description="Here's a longer description of the custom **OpenAPI** schema",
        routes=app.routes,
    )
    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


def _make_db_client_factory(engine) -> ClientFactory:
    """Returns a ClientFactory that looks up SiteCredential from the DB
    before falling back to an anonymous WikiSettings."""

    def _factory(site: Site) -> WikiClient:
        with Session(engine) as session:
            cred = session.exec(
                select(SiteCredential).where(SiteCredential.site_pk == site.pk)
            ).first()
        overrides: dict = {}
        if cred:
            overrides = dict(
                username=cred.username,
                password=cred.password,
                bot_name=cred.bot_name,
            )
        return get_wiki_client(WikiSettings.from_site(site, **overrides))

    return _factory


def create_app(
    engine: Engine | None = None,
    client_factory: ClientFactory | None = None,
    blob_root: Path | str | None = None,
    logging_config: LoggingConfig = LOGGING_CONFIG,
) -> FastAPI:
    """Build the app. Pass an ``engine`` to point at a different database, a
    ``client_factory`` to inject a fake wiki client, and a ``blob_root`` for
    the file-blob download cache (all three are used by tests)."""
    configure_logging(logging_config)
    engine = engine or create_db_engine(echo=configured_sqlalchemy_echo(logging_config))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(
        title="wtbot",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.openapi = custom_openapi

    app.state.engine = engine
    app.state.client_factory = client_factory or _make_db_client_factory(engine)
    app.state.blob_root = (
        Path(blob_root)
        if blob_root is not None
        else Path(os.environ.get("WTBOT_BLOB_ROOT", "./blobs"))
    )

    app.include_router(health.router)
    app.include_router(annotations.router)
    app.include_router(commit_api.router)
    app.include_router(edit_journal.router)
    app.include_router(fetch.router)
    app.include_router(file_blob.router)
    app.include_router(namespace.router)
    app.include_router(page_image.router)
    app.include_router(page_meta.router)
    app.include_router(page_nav.router)
    app.include_router(pages.router)
    app.include_router(preview.router)
    app.include_router(sites.router)
    app.include_router(vfs.router)
    app.include_router(viewer.router)

    return app


app = create_app()
