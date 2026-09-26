from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from wtbot.fetch.fetch_worker import run_pending
from wtbot.model import (
    FetchRequest,
    FetchState,
    FetchStatus,
    FileBlob,
    IndexMeta,
    Page,
    Site,
    Title,
)
from wtbot.shared_repository import (
    ensure_shared_repository_site,
    shared_repository_site,
)
from wtbot.sync import _file_of
from wtbot.vfs import WikisourceVfs
from wtbot.vfs.store import PageStore
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

"""A scan served from Commons is Commons's page, fetched on Commons's site.

The local wiki holds no page at ``File:X`` (``missing``, ``known``,
``imagerepository: shared``); the fetch records that, repoints the index at
Commons's title, and queues the real fetch there -- where the page has ids and
the blob hangs off it.
"""

INDEX = "Index:Scan.djvu"
FILE = "File:Scan.djvu"
SCAN = b"%DJVU fake bytes"


def _file_on_commons() -> RemotePage:
    return RemotePage(
        title=FILE,
        namespace_key=6,
        namespace_canonical="File",
        content_model="wikitext",
        text="== Summary ==",
        pageid=46260330,
        revid=900,
    )


@pytest.fixture
def sites(engine: Engine) -> tuple[Site, Site]:
    ensure_shared_repository_site(engine)
    with Session(engine) as session:
        local = Site(family="wikisource", code="en", label="en")
        session.add(local)
        session.commit()
        session.refresh(local)
        commons = shared_repository_site(session)
        assert commons is not None
        return local, commons


def _index_named_locally(session: Session, site: Site) -> IndexMeta:
    index = Title(
        site_pk=site.pk, title=INDEX, expected_content_model="proofread-index"
    )
    session.add(index)
    session.flush()
    return PageStore(session).ensure_index_meta(index)


def test_startup_registers_commons_once_without_a_credential(engine: Engine) -> None:
    ensure_shared_repository_site(engine)
    ensure_shared_repository_site(engine)
    with Session(engine) as session:
        [site] = session.exec(select(Site)).all()
        assert (site.family, site.code, site.label) == ("commons", "commons", "commons")


def test_commons_does_not_take_a_label_already_in_use(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Site(family="mywikisource", code="en", label="commons"))
        session.commit()
    ensure_shared_repository_site(engine)
    with Session(engine) as session:
        assert shared_repository_site(session).label is None


def test_a_new_index_names_its_file_on_its_own_site(engine: Engine, sites) -> None:
    local, _ = sites
    with Session(engine) as session:
        meta = _index_named_locally(session, local)
        file = session.get(Title, meta.file_title_pk)
        assert (file.site_pk, file.title) == (local.pk, FILE)
        assert session.get(Page, file.pk) is None  # named, not fetched


def test_a_shared_file_is_fetched_on_commons(
    engine: Engine, sites, tmp_path: Path
) -> None:
    local, commons = sites
    with Session(engine) as session:
        meta = _index_named_locally(session, local)
        session.add(FetchRequest(site_pk=local.pk, title=FILE))
        session.commit()
        index_pk = meta.title_pk

        wikisource = FakeWikiClient(shared_files={FILE})
        commons_wiki = FakeWikiClient(
            pages={FILE: _file_on_commons()}, files={FILE: SCAN}
        )
        clients = {local.pk: wikisource, commons.pk: commons_wiki}
        run_pending(session, lambda site: clients[site.pk], blob_root=tmp_path)

        # The local request found out where the page is, and queued the fetch
        # on Commons, which the same drain then ran...
        requests = session.exec(select(FetchRequest).order_by(FetchRequest.pk)).all()
        assert [(r.site_pk, r.title, r.status) for r in requests] == [
            (local.pk, FILE, FetchStatus.done),
            (commons.pk, FILE, FetchStatus.done),
        ]
        local_file = session.exec(
            select(Title).where(Title.site_pk == local.pk, Title.title == FILE)
        ).one()
        assert local_file.fetch_status == FetchState.done
        assert session.get(Page, local_file.pk) is None

        # ...the index now names Commons's title...
        meta = session.get(IndexMeta, index_pk)
        commons_file = session.get(Title, meta.file_title_pk)
        assert commons_file.site_pk == commons.pk

        # ...writing a page with real ids, blob and all.
        page = session.get(Page, commons_file.pk)
        assert (page.pageid, page.revid) == (46260330, 900)
        blob = session.exec(
            select(FileBlob).where(FileBlob.page_pk == commons_file.pk)
        ).one()
        assert _file_of(session, session.get(Title, index_pk)) == (FILE, blob)


def test_a_local_upload_shadows_the_shared_file(engine: Engine, sites) -> None:
    """MediaWiki looks locally first: a file uploaded to the index's own wiki
    wins, and the fetch moves the reference back."""
    local, commons = sites
    with Session(engine) as session:
        meta = _index_named_locally(session, local)
        on_commons = Title(
            site_pk=commons.pk, title=FILE, expected_content_model="wikitext"
        )
        session.add(on_commons)
        session.flush()
        meta.file_title_pk = on_commons.pk
        session.add(FetchRequest(site_pk=local.pk, title=FILE))
        session.commit()
        index_pk = meta.title_pk

        uploaded = FakeWikiClient(pages={FILE: _file_on_commons()})
        run_pending(session, lambda site: uploaded)

        file = session.get(Title, session.get(IndexMeta, index_pk).file_title_pk)
        assert file.site_pk == local.pk


def test_the_index_directory_shows_the_file_where_it_lives(
    engine: Engine, sites
) -> None:
    local, commons = sites
    with Session(engine) as session:
        meta = _index_named_locally(session, local)
        on_commons = Title(
            site_pk=commons.pk, title=FILE, expected_content_model="wikitext"
        )
        session.add(on_commons)
        session.flush()
        meta.file_title_pk = on_commons.pk
        session.commit()

        vfs = WikisourceVfs(session)
        children = vfs.list_children(f"/wikisource/en/{INDEX}").children
        assert f"/wikisource/en/{INDEX}/{FILE}" in [c.path for c in children]
        stat = vfs.stat(f"/wikisource/en/{INDEX}/{FILE}/wikitext")
        assert stat.exists
