import base64
from pathlib import Path

import pytest
from sqlmodel import Session

from ide_test_support.__main__ import seed_browser
from wtbot.db import create_db_engine
from wtbot.vfs import WikisourceVfs


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
