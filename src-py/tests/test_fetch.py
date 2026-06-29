"""End-to-end of the cache-fill path with a network-free fake wiki client:
enqueue via the API -> worker drains -> page written back to SQLite."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.sqlmodel import FetchRequest, FetchStatus, FileBlob, Page
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.types import RemotePage

_INDEX_TITLE = "Index:Tractatus.djvu"
_FILE_TITLE = "File:Tractatus.djvu"
_FAKE_FILE_BYTES = b"%PDF-fake"


def _remote(title, content_model, ns_canonical, ns_key, text=None):
    return RemotePage(
        title=title,
        namespace_key=ns_key,
        namespace_canonical=ns_canonical,
        content_model=content_model,
        text=text or "{{:MediaWiki:Proofreadpage_index_template|...}}",
        pageid=42,
        revid=23417,
        user="someeditor",
        comment="tweak",
        sha1="7ea25a6970ea3470958843030de6e38783beeeda",
        size=2601,
    )


def _page_remote(n: int) -> RemotePage:
    return RemotePage(
        title=f"Page:Tractatus.djvu/{n}",
        namespace_key=250,
        namespace_canonical="Page",
        content_model="proofread-page",
        text=f"page {n} content",
        pageid=100 + n,
        revid=1000 + n,
        user="bot",
        comment=f"page {n}",
        sha1=f"sha{n:040d}",
        size=200,
    )


@pytest.fixture
def index_remote():
    return _remote(
        "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu",
        "proofread-index",
        "Index",
        252,
    )


@pytest.fixture
def app_with_fake(engine, index_remote):
    client = FakeWikiClient(pages={index_remote.title: index_remote})
    app = create_app(engine=engine, client_factory=lambda site: client)
    with TestClient(app) as c:
        yield c, index_remote


@pytest.fixture
def index_remote_with_pagelist():
    """Index page whose body contains a <pagelist> with 3 pages."""
    return _remote(
        _INDEX_TITLE,
        "proofread-index",
        "Index",
        252,
        text='{{Header}}\n<pagelist 1to3="1" to="3" />\n',
    )


@pytest.fixture
def app_with_index_fanout(engine, tmp_path, index_remote_with_pagelist):
    pages = {
        index_remote_with_pagelist.title: index_remote_with_pagelist,
        **{f"Page:Tractatus.djvu/{n}": _page_remote(n) for n in range(1, 4)},
    }
    files = {_FILE_TITLE: _FAKE_FILE_BYTES}
    wiki = FakeWikiClient(pages=pages, files=files)
    app = create_app(
        engine=engine,
        client_factory=lambda site: wiki,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as c:
        yield c, index_remote_with_pagelist, tmp_path


def test_fetch_enqueues_drains_and_persists(app_with_fake, engine):
    client, index_remote = app_with_fake
    resp = client.post(
        "/fetch/",
        json={
            "title": index_remote.title,
            "family": "mywikisource",
            "code": "en",
            "api_url": "https://wikisource-debian-13.lan/w/api.php",
            "kind": "single",
        },
    )
    assert resp.status_code == 202
    body = resp.json()

    # The request was driven to completion inline.
    assert body["request"]["status"] == FetchStatus.done.value
    assert body["request"]["progress_done"] == 1

    # The page was written back to SQLite with the remote snapshot.
    page = body["page"]
    assert page is not None
    assert page["content_model"] == "proofread-index"
    assert page["namespace_role"] == "index"  # role resolved from canonical 'Index'
    assert page["revid"] == 23417
    assert page["dirty"] is False

    # And it is actually in the database, not just echoed.
    from sqlmodel import Session, select

    with Session(engine) as s:
        rows = s.exec(select(Page).where(Page.title == index_remote.title)).all()
        assert len(rows) == 1
        assert rows[0].sha1 == index_remote.sha1


def test_fetch_missing_page_records_error(engine):
    client = FakeWikiClient(pages={})  # nothing exists
    app = create_app(engine=engine, client_factory=lambda site: client)
    with TestClient(app) as c:
        resp = c.post(
            "/fetch/",
            json={"title": "Index:Nope.djvu", "family": "mywikisource", "code": "en"},
        )
    body = resp.json()
    assert body["request"]["status"] == FetchStatus.error.value
    assert "not found" in body["request"]["error_message"]
    assert body["page"] is None


def test_get_fetch_request(app_with_fake):
    client, index_remote = app_with_fake
    pk = client.post(
        "/fetch/",
        json={"title": index_remote.title, "family": "mywikisource", "code": "en"},
    ).json()["request"]["pk"]

    got = client.get(f"/fetch/{pk}")
    assert got.status_code == 200
    assert got.json()["pk"] == pk

    assert client.get("/fetch/9999").status_code == 404


def test_refetch_updates_in_place(app_with_fake, engine):
    """Two fetches of the same title yield one row, not two."""
    client, index_remote = app_with_fake
    payload = {"title": index_remote.title, "family": "mywikisource", "code": "en"}
    client.post("/fetch/", json=payload)
    client.post("/fetch/", json=payload)

    with Session(engine) as s:
        rows = s.exec(select(Page).where(Page.title == index_remote.title)).all()
        assert len(rows) == 1


def test_index_fanout_creates_pages_and_children(app_with_index_fanout, engine):
    """depth=1 on a proofread-index: index + 3 page children are all fetched."""
    client, index_remote, tmp_path = app_with_index_fanout
    resp = client.post(
        "/fetch/",
        json={
            "title": _INDEX_TITLE,
            "family": "mywikisource",
            "code": "en",
            "depth": 1,
            # kind omitted — fan-out is driven by content_model, not kind
        },
    )
    assert resp.status_code == 202
    body = resp.json()

    # Parent request ends done after all children drain.
    req = body["request"]
    assert req["status"] == FetchStatus.done.value
    assert req["progress_total"] == 4  # 1 index + 3 pages
    assert req["progress_done"] == 4

    # Index page carries page_count (from <pagelist> wikitext).
    page = body["page"]
    assert page is not None
    assert page["page_count"] == 3

    # Blob was written to the configured blob_root.
    blob_file = tmp_path / "blobs" / "mywikisource" / "en" / "Tractatus.djvu"
    assert blob_file.exists()
    assert blob_file.read_bytes() == _FAKE_FILE_BYTES

    # 4 FetchRequests: the parent + 3 children.
    with Session(engine) as s:
        all_reqs = s.exec(select(FetchRequest)).all()
        assert len(all_reqs) == 4
        parent = next(r for r in all_reqs if r.parent_pk is None)
        children = [r for r in all_reqs if r.parent_pk == parent.pk]
        assert len(children) == 3
        assert all(c.status == FetchStatus.done for c in children)

    # 4 Page rows: index + pages 1, 2, 3.
    with Session(engine) as s:
        pages = s.exec(select(Page)).all()
        assert len(pages) == 4
        titles = {p.title for p in pages}
        assert _INDEX_TITLE in titles
        for n in range(1, 4):
            assert f"Page:Tractatus.djvu/{n}" in titles

    # FileBlob row exists for the index (via the File: download).
    with Session(engine) as s:
        index_page = s.exec(select(Page).where(Page.title == _INDEX_TITLE)).one()
        file_blobs = s.exec(select(FileBlob).where(FileBlob.page_pk == index_page.pk)).all()
        assert len(file_blobs) == 1
        fb = file_blobs[0]
        assert fb.mime == "image/vnd.djvu"
        assert fb.size == len(_FAKE_FILE_BYTES)
        assert fb.local_path is not None
        assert fb.local_path == str(blob_file)


def test_index_fanout_no_pagelist_creates_no_children(engine, tmp_path):
    """If the index body has no <pagelist>, no children are created."""
    index = _remote(_INDEX_TITLE, "proofread-index", "Index", 252)
    wiki = FakeWikiClient(pages={_INDEX_TITLE: index})
    app = create_app(
        engine=engine,
        client_factory=lambda site: wiki,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as c:
        body = c.post(
            "/fetch/",
            json={
                "title": _INDEX_TITLE,
                "family": "mywikisource",
                "code": "en",
                "depth": 1,
            },
        ).json()

    assert body["request"]["status"] == FetchStatus.done.value
    with Session(engine) as s:
        assert len(s.exec(select(FetchRequest)).all()) == 1  # just the parent
        assert len(s.exec(select(Page)).all()) == 1  # just the index


def test_file_fetch_downloads_blob(engine, tmp_path):
    """Fetching a File: page downloads the binary blob regardless of depth."""
    file_remote = RemotePage(
        title=_FILE_TITLE,
        namespace_key=6,
        namespace_canonical="File",
        content_model="wikitext",  # MediaWiki reports wikitext for the description page
        text="[[Category:DjVu files]]",
        pageid=7,
        revid=999,
        user="uploader",
        comment="upload",
        sha1="a" * 40,
        size=100,
    )
    wiki = FakeWikiClient(
        pages={_FILE_TITLE: file_remote}, files={_FILE_TITLE: _FAKE_FILE_BYTES}
    )
    app = create_app(
        engine=engine,
        client_factory=lambda site: wiki,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as c:
        body = c.post(
            "/fetch/",
            json={"title": _FILE_TITLE, "family": "mywikisource", "code": "en"},
        ).json()

    assert body["request"]["status"] == FetchStatus.done.value
    page = body["page"]
    assert page is not None
    assert page["namespace_role"] == "file"

    blob_file = tmp_path / "blobs" / "mywikisource" / "en" / "Tractatus.djvu"
    assert blob_file.exists()
    assert blob_file.read_bytes() == _FAKE_FILE_BYTES

    # FileBlob carries the stat-like metadata.
    with Session(engine) as s:
        file_page = s.exec(select(Page).where(Page.title == _FILE_TITLE)).one()
        fb = s.exec(select(FileBlob).where(FileBlob.page_pk == file_page.pk)).one()
        assert fb.mime == "image/vnd.djvu"
        assert fb.size == len(_FAKE_FILE_BYTES)
        assert fb.file_sha1 is not None and len(fb.file_sha1) == 40
        assert fb.local_path == str(blob_file)
        assert fb.downloaded_at is not None
