import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, Response
from sqlalchemy import Engine
from sqlmodel import Session

from wtbot.db import create_db_engine, init_db
from wtbot.main import create_app
from wtbot.model import Page, ProofreadPageMeta, Site
from wtbot.model.wiki.title import FetchState
from wtbot.title_store import ensure_title
from wtbot.vfs.nodes import AspectLeaf, resolve
from wtbot.vfs.store import PageStore


def add_test_controls(app: FastAPI, engine: Engine) -> None:
    """Revision injection exists only in this test-owned app, never wtbot.main."""

    @dataclass(frozen=True)
    class Stall:
        method: str = ""
        path: str = ""
        seconds: float = 0

    stall = Stall()

    @app.middleware("http")
    async def stall_before_handler(request: Request, call_next):
        active = stall
        if (
            active.seconds > 0
            and request.method == active.method
            and request.url.path == active.path
        ):
            await asyncio.sleep(active.seconds)
            # This fault never reaches the write handler, even if the client timed out.
            return Response("Test request stalled before execution", status_code=504)
        return await call_next(request)

    @app.post("/__ide_test/stall", status_code=204, response_class=Response)
    def configure_stall(method: str = "", path: str = "", seconds: float = 0) -> None:
        nonlocal stall
        if seconds < 0 or seconds > 30:
            raise HTTPException(400, "Test stall must be between 0 and 30 seconds")
        stall = Stall(method, path, seconds)

    @app.post("/__ide_test/revise", status_code=204, response_class=Response)
    def revise(
        path: str, revid: int, text: Annotated[str, Body(media_type="text/plain")]
    ) -> None:
        with Session(engine) as session:
            node = resolve(PageStore(session), path)
            if not isinstance(node, AspectLeaf) or node.node.entry is None:
                raise HTTPException(404, "Unknown test page")
            page = session.get(Page, node.node.entry.pk)
            if page is None:
                raise HTTPException(404, "Unknown test page revision")
            page.text = text
            page.revid = revid
            page.remote_timestamp = datetime.now(UTC)
            session.add(page)
            session.commit()


@dataclass(frozen=True)
class BrowserScenario:
    family: str = "ide"
    code: str = "en"
    index_title: str = "Index:IDE integration.djvu"


def seed_browser(database: Path, index_last_page: int = 2) -> BrowserScenario:
    """Construct cache data with today's schema, without contacting a wiki."""
    if database.exists():
        raise FileExistsError(f"Refusing to seed an existing database: {database}")
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(f"sqlite:///{database.resolve()}")
    scenario = BrowserScenario()
    try:
        init_db(engine)
        with Session(engine) as session:
            site = Site(label="ide-test", family=scenario.family, code=scenario.code)
            session.add(site)
            session.flush()
            assert site.pk is not None
            index = ensure_title(
                session,
                site_pk=site.pk,
                title=scenario.index_title,
                expected_content_model="proofread-index",
            )
            index.namespace_key = 252
            index.fetch_status = FetchState.done
            session.add(
                Page(
                    pk=index.pk,
                    site_pk=site.pk,
                    content_model="proofread-index",
                    text=f'<pagelist from="1" to="{index_last_page}" />',
                    pageid=1,
                    revid=101,
                    remote_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            for number in (1, 2):
                title = ensure_title(
                    session,
                    site_pk=site.pk,
                    title=f"Page:IDE integration.djvu/{number}",
                    expected_content_model="proofread-page",
                )
                title.namespace_key = 250
                title.fetch_status = FetchState.done
                session.add(
                    Page(
                        pk=title.pk,
                        site_pk=site.pk,
                        content_model="proofread-page",
                        text=f'<noinclude><pagequality level="1" user="IDE test" /></noinclude>\nIntegration page {number}.\n<noinclude></noinclude>',
                        pageid=number + 1,
                        revid=101 + number,
                        remote_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                )
                session.add(
                    ProofreadPageMeta(
                        title_pk=title.pk,
                        index_title_pk=index.pk,
                        page_number=number,
                        quality_level=1,
                    )
                )
            session.commit()
    finally:
        engine.dispose()
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a fresh IDE test scenario.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18594)
    parser.add_argument("--scenario", choices=["browser"], default="browser")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Restart this test's existing database without reseeding.",
    )
    parser.add_argument("--index-last-page", type=int, default=2)
    args = parser.parse_args()
    database = args.data_dir.resolve() / "wtbot.db"
    if args.resume:
        if not database.is_file():
            raise FileNotFoundError(f"No IDE test database to resume: {database}")
    else:
        seed_browser(database, args.index_last_page)
    engine = create_db_engine(f"sqlite:///{database}")
    try:
        app = create_app(engine=engine, blob_root=args.data_dir / "blobs")
        add_test_controls(app, engine)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
