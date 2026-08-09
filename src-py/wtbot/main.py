import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from wtbot.api import (
    annotations,
    edit_journal,
    fetch,
    file_blob,
    health,
    links,
    locator_index,
    namespace,
    ocr,
    page_meta,
    page_nav,
    pages,
    preview,
    reference_image,
    sites,
    sync,
    vfs,
    viewer,
    works,
)
from wtbot.api import (
    commit as commit_api,
)
from wtbot.api.errors import register_error_handlers
from wtbot.db import create_db_engine, init_db
from wtbot.logging_config import LOGGING_CONFIG, LoggingConfig, configure_logging
from wtbot.logging_config import sqlalchemy_echo as configured_sqlalchemy_echo
from wtbot.model import Site, SiteCredential
from wtbot.settings import WikiSettings
from wtbot.site_store import AnonymousAccessRefused, anonymous_allowed
from wtbot.wiki.client_registry import make_client_factory
from wtbot.worker import ClientFactory

"""wtbot FastAPI application.

This is the plugin-facing contract: a thin FastAPI app over the SQLite cache.
Surfaces (VFS, cache-fill, commit) are described in ``src-py/DESIGN.md``; only a
health check and a sites vertical slice are wired up so far.
"""


def _settings_for_site(engine):
    """Resolve a Site row to WikiSettings, taking credentials from the DB.

    Refuses to build anonymous settings unless WTBOT_ALLOW_ANONYMOUS says so.
    The endpoints check the same thing when work is queued, which is where the
    error is useful; this is the check that cannot be gone around -- a request
    queued before a credential was removed, or work reaching the worker by any
    other route, still stops here rather than going out unauthenticated.
    """

    def _resolve(site: Site) -> WikiSettings:
        with Session(engine) as session:
            cred = session.exec(
                select(SiteCredential).where(SiteCredential.site_pk == site.pk)
            ).first()
        if cred is None:
            if not anonymous_allowed():
                raise AnonymousAccessRefused(site.label or f"{site.family}:{site.code}")
            return WikiSettings.from_site(site)
        return WikiSettings.from_site(
            site,
            username=cred.username,
            password=cred.password,
            bot_name=cred.bot_name,
        )

    return _resolve


def _make_db_client_factory(engine) -> ClientFactory:
    """A ClientFactory that reads SiteCredential from the DB and reuses one
    client per (site, credential) for the life of the process.

    Reuse is the point, not an optimisation: each construction re-detects the
    site over HTTP and logs in again, so a client per fetch request spent most
    of our rate-limit allowance on setup. See wtbot.wiki.client_registry.
    """
    return make_client_factory(_settings_for_site(engine))


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
    # Migrate synchronously so callers can use the returned app immediately.
    # Leaving this in lifespan as well keeps a real ASGI boot self-healing.
    init_db(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(
        title="wtbot",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_error_handlers(app)

    app.state.engine = engine
    app.state.client_factory = client_factory or _make_db_client_factory(engine)
    app.state.blob_root = (
        Path(blob_root)
        if blob_root is not None
        else Path(os.environ.get("WTBOT_BLOB_ROOT", "./blobs"))
    )

    app.include_router(health.router)
    app.include_router(commit_api.router)
    app.include_router(edit_journal.router)
    app.include_router(fetch.router)
    # Before `links`: /links/works must not be matched by
    # DELETE /links/{link_pk}, which would 422 on parsing "works" as an int.
    app.include_router(works.router)
    app.include_router(links.router)
    app.include_router(file_blob.router)
    app.include_router(namespace.router)
    app.include_router(preview.router)
    app.include_router(reference_image.router)
    app.include_router(sites.router)
    app.include_router(sync.router)
    app.include_router(vfs.router)
    app.include_router(viewer.router)

    # ORDER IS LOAD-BEARING for the routers sharing the /pages prefix.
    # Routes are matched first-registered-wins (Starlette), and
    # `pages.router` owns the catch-all `GET /pages/{page_pk}`. Every router
    # contributing a *static* /pages/<segment> route must be registered
    # before it, or that segment is swallowed by {page_pk} and 422s on the
    # int parse. `test_route_order.py` pins this.
    # /pages/{annotations,text-anchors,box-links}
    app.include_router(annotations.router)
    app.include_router(ocr.router)  # /ocr/* and /pages/ocr/*
    app.include_router(page_meta.router)  # /pages/resolve, /pages/{pk}/*-meta
    app.include_router(page_nav.router)  # /pages/nav
    app.include_router(locator_index.router)  # /locator-index/{sections,page-numbers}
    app.include_router(pages.router)  # /pages/, /pages/{page_pk} — must be last

    return app


app = create_app()
