import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ide_test_support.__main__ import add_test_controls, seed_browser, seed_search_work
from wtbot.db import create_db_engine
from wtbot.main import create_app
from wtbot.model import EditJournal, Page, Title
from wtbot.vfs import WikisourceVfs


def test_test_owned_revision_control(tmp_path: Path) -> None:
    database = tmp_path / "wtbot.db"
    seed_browser(database)
    engine = create_db_engine(f"sqlite:///{database}")
    try:
        app = create_app(engine=engine, blob_root=tmp_path / "blobs")
        with TestClient(app) as client:
            assert client.post("/__ide_test/revise").status_code == 404
        app = create_app(engine=engine, blob_root=tmp_path / "blobs")
        add_test_controls(app, engine)
        with TestClient(app) as client:
            path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            result = client.post(
                "/__ide_test/revise",
                params={"path": path, "revid": 202},
                content="Externally revised",
                headers={"Content-Type": "text/plain"},
            )
            assert result.status_code == 204, result.text
            read = client.get("/vfs/content", params={"path": path}).json()
            assert read["revid"] == 202
            assert (
                base64.b64decode(read["content_base64"]).decode()
                == "Externally revised"
            )
    finally:
        engine.dispose()


def test_browser_scenario_exposes_index_and_two_readable_pages(tmp_path: Path) -> None:
    database = tmp_path / "wtbot.db"
    seed_browser(database)
    engine = create_db_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            vfs = WikisourceVfs(session)
            index = "/ide/en/Index/IDE integration.djvu"
            assert vfs.stat(index).content_model == "proofread-index"
            pages = vfs.list_children(f"{index}/@pages").children
            assert len(pages) == 2
            for number, page in enumerate(pages, start=1):
                assert page.quality_level == 1
                content = vfs.read(f"{page.path}/@wikitext")
                text = base64.b64decode(content.content_base64).decode()
                assert f"Integration page {number}." in text
            assert (
                session.connection().exec_driver_sql("PRAGMA foreign_key_check").all()
                == []
            )
        # Reruns must create a new directory rather than duplicating/overwriting data.
        with pytest.raises(FileExistsError):
            seed_browser(database)
        with Session(engine) as session:
            assert (
                len(WikisourceVfs(session).list_children(f"{index}/@pages").children)
                == 2
            )
    finally:
        engine.dispose()


def test_search_scenario_distinguishes_defaults_from_saved_local_transcriptions(
    tmp_path: Path,
) -> None:
    database = tmp_path / "search.db"
    seed_search_work(database)
    engine = create_db_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            vfs = WikisourceVfs(session)
            prefix = "/ide/en/Page/IDE integration.djvu"
            stats = vfs.stat_bulk([f"{prefix}/{n}/@wikitext" for n in (1, 2, 3, 4, 5)])
            assert [(s.placeholder, s.dirty) for s in stats] == [
                (False, False),
                (False, False),
                (True, False),
                (True, False),
                (True, True),
            ]
            defaults = [
                session.exec(
                    select(Title).where(Title.title == f"Page:IDE integration.djvu/{n}")
                ).one()
                for n in (3, 4)
            ]
            assert all(session.get(Page, title.pk) is None for title in defaults)
            assert all(
                session.exec(
                    select(EditJournal).where(EditJournal.title_pk == title.pk)
                ).first()
                is None
                for title in defaults
            )
            assert len(session.exec(select(EditJournal)).all()) == 1
    finally:
        engine.dispose()
