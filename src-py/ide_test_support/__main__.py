import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from sqlmodel import Session

from wtbot.db import create_db_engine, init_db
from wtbot.main import create_app
from wtbot.model import Page, ProofreadPageMeta, Site
from wtbot.model.wiki.title import FetchState
from wtbot.title_store import ensure_title


@dataclass(frozen=True)
class BrowserScenario:
    family: str = "ide"
    code: str = "en"
    index_title: str = "Index:IDE integration.djvu"


def seed_browser(database: Path) -> BrowserScenario:
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
                    text='<pagelist from="1" to="2" />',
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
    args = parser.parse_args()
    database = args.data_dir.resolve() / "wtbot.db"
    seed_browser(database)
    engine = create_db_engine(f"sqlite:///{database}")
    try:
        uvicorn.run(
            create_app(engine=engine, blob_root=args.data_dir / "blobs"),
            host="127.0.0.1",
            port=args.port,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
