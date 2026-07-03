"""End-to-end of the cache-fill path with a network-free fake wiki client:
enqueue via the API -> worker drains -> page written back to SQLite."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import FetchRequest, FetchStatus, FileBlob, Page, PageMeta, Site
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage, RemotePageImages
from wtbot.worker import run_pending

_INDEX_TITLE = "Index:Tractatus.djvu"
_FILE_TITLE = "File:Tractatus.djvu"
_FAKE_FILE_BYTES = b"%PDF-fake"


class GetPageHookClient(FakeWikiClient):
    def __init__(self, *args, on_get_page, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_get_page = on_get_page

    def get_page(self, title: str) -> RemotePage:
        self._on_get_page()
        return super().get_page(title)


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


def _index_subpage_remote(title: str) -> RemotePage:
    return RemotePage(
        title=title,
        namespace_key=252,
        namespace_canonical="Index",
        content_model="sanitized-css",
        text=".pagetext { font-variant-numeric: oldstyle-nums; }",
        pageid=700,
        revid=1700,
        user="bot",
        comment="styles",
        sha1="c" * 40,
        size=50,
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
    asset_title = f"{_INDEX_TITLE}/styles.css"
    pages = {
        index_remote_with_pagelist.title: index_remote_with_pagelist,
        asset_title: _index_subpage_remote(asset_title),
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
    """depth=1 on a proofread-index fetches page children and index subpages."""
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
    assert req["progress_total"] == 5  # 1 index + 3 pages + styles.css
    assert req["progress_done"] == 5

    # Index page carries page_count (from <pagelist> wikitext).
    page = body["page"]
    assert page is not None
    assert page["page_count"] == 3

    # Blob was written to the configured blob_root.
    blob_file = tmp_path / "blobs" / "mywikisource" / "en" / "Tractatus.djvu"
    assert blob_file.exists()
    assert blob_file.read_bytes() == _FAKE_FILE_BYTES

    # 5 FetchRequests: the parent + 3 page children + 1 index asset child.
    with Session(engine) as s:
        all_reqs = s.exec(select(FetchRequest)).all()
        assert len(all_reqs) == 5
        parent = next(r for r in all_reqs if r.parent_pk is None)
        children = [r for r in all_reqs if r.parent_pk == parent.pk]
        assert len(children) == 4
        assert {c.title for c in children} == {
            "Page:Tractatus.djvu/1",
            "Page:Tractatus.djvu/2",
            "Page:Tractatus.djvu/3",
            f"{_INDEX_TITLE}/styles.css",
        }
        assert all(c.status == FetchStatus.done for c in children)

    # 5 Page rows: index + pages 1, 2, 3 + styles.css.
    with Session(engine) as s:
        pages = s.exec(select(Page)).all()
        assert len(pages) == 5
        titles = {p.title for p in pages}
        assert _INDEX_TITLE in titles
        assert f"{_INDEX_TITLE}/styles.css" in titles
        for n in range(1, 4):
            assert f"Page:Tractatus.djvu/{n}" in titles
        page_one = next(p for p in pages if p.title == "Page:Tractatus.djvu/1")
        assert page_one.text == "page 1 content"
        assert page_one.content_model == "proofread-page"
        styles = next(p for p in pages if p.title == f"{_INDEX_TITLE}/styles.css")
        assert styles.text == ".pagetext { font-variant-numeric: oldstyle-nums; }"
        assert styles.content_model == "sanitized-css"

    # FileBlob row exists for the index (via the File: download).
    with Session(engine) as s:
        index_page = s.exec(select(Page).where(Page.title == _INDEX_TITLE)).one()
        file_blobs = s.exec(
            select(FileBlob).where(FileBlob.page_pk == index_page.pk)
        ).all()
        assert len(file_blobs) == 1
        fb = file_blobs[0]
        assert fb.mime == "image/vnd.djvu"
        assert fb.size == len(_FAKE_FILE_BYTES)
        assert fb.local_path is not None
        assert fb.local_path == str(blob_file)


def test_worker_index_fanout_queues_index_subpages(
    session, tmp_path, index_remote_with_pagelist
):
    asset_title = f"{_INDEX_TITLE}/styles.css"
    pages = {
        index_remote_with_pagelist.title: index_remote_with_pagelist,
        asset_title: _index_subpage_remote(asset_title),
        **{f"Page:Tractatus.djvu/{n}": _page_remote(n) for n in range(1, 4)},
    }
    wiki = FakeWikiClient(pages=pages, files={_FILE_TITLE: _FAKE_FILE_BYTES})
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(FetchRequest(site_pk=site.pk, title=_INDEX_TITLE, depth=1))
    session.commit()

    handled = run_pending(
        session,
        lambda _: wiki,
        limit=10,
        blob_root=tmp_path / "blobs",
    )

    assert handled == 5
    req = session.exec(
        select(FetchRequest).where(
            FetchRequest.title == _INDEX_TITLE,
            FetchRequest.parent_pk.is_(None),
        )
    ).one()
    assert req.status == FetchStatus.done
    assert req.progress_total == 5
    assert req.progress_done == 5
    assert {
        r.title
        for r in session.exec(
            select(FetchRequest).where(FetchRequest.parent_pk == req.pk)
        )
    } == {
        "Page:Tractatus.djvu/1",
        "Page:Tractatus.djvu/2",
        "Page:Tractatus.djvu/3",
        asset_title,
    }
    assert {p.title for p in session.exec(select(Page)).all()} == {
        _INDEX_TITLE,
        "Page:Tractatus.djvu/1",
        "Page:Tractatus.djvu/2",
        "Page:Tractatus.djvu/3",
        asset_title,
    }
    styles = session.exec(select(Page).where(Page.title == asset_title)).one()
    assert styles.index_title == _INDEX_TITLE
    assert styles.page_number is None


def test_proofread_page_metadata_uses_content_model(session):
    remote = RemotePage(
        title="Page:Tractatus.djvu/7",
        namespace_key=999,
        namespace_canonical="Other",
        content_model="proofread-page",
        text="page content",
        pageid=107,
        revid=1007,
        sha1="d" * 40,
        size=200,
    )
    wiki = FakeWikiClient(pages={remote.title: remote})
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(FetchRequest(site_pk=site.pk, title=remote.title))
    session.commit()

    assert run_pending(session, lambda _: wiki) == 1
    page = session.exec(select(Page).where(Page.title == remote.title)).one()
    assert page.index_title == "Index:Tractatus.djvu"
    assert page.page_number == 7


def test_proofread_page_fetch_populates_page_meta(session):
    """Fetching a proofread-page pulls the ProofreadPage scan-image URLs and
    quality (prop=imageforpage|proofread) into PageMeta / Page.quality_level."""
    title = "Page:Tractatus.djvu/45"
    remote = RemotePage(
        title=title,
        namespace_key=104,
        namespace_canonical="Page",
        content_model="proofread-page",
        text="page content",
        pageid=145,
        revid=1045,
    )
    wiki = FakeWikiClient(
        pages={title: remote},
        page_images={
            title: RemotePageImages(
                thumbnail_url="https://upload.example/thumb/page45-500px.jpg",
                fullsize_url="https://upload.example/full/page45.jpg",
                size=1280,
                filename="Tractatus.djvu",
                quality=1,
                quality_text="Not proofread",
            )
        },
    )
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(FetchRequest(site_pk=site.pk, title=title))
    session.commit()

    assert run_pending(session, lambda _: wiki) == 1

    page = session.exec(select(Page).where(Page.title == title)).one()
    assert page.quality_level == 1
    meta = session.exec(
        select(PageMeta).where(PageMeta.page_pk == page.pk)
    ).one()
    assert meta.thumb_url == "https://upload.example/thumb/page45-500px.jpg"
    assert meta.source_image_url == "https://upload.example/full/page45.jpg"


def test_proofread_page_fetch_without_images_creates_no_page_meta(session):
    """A wiki without the ProofreadPage image API (FakeWikiClient default)
    must not fail the fetch or leave an empty PageMeta row behind."""
    title = "Page:Tractatus.djvu/46"
    remote = RemotePage(
        title=title,
        namespace_key=104,
        namespace_canonical="Page",
        content_model="proofread-page",
        text="page content",
        pageid=146,
        revid=1046,
    )
    wiki = FakeWikiClient(pages={title: remote})
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(FetchRequest(site_pk=site.pk, title=title))
    session.commit()

    assert run_pending(session, lambda _: wiki) == 1

    page = session.exec(select(Page).where(Page.title == title)).one()
    assert page.fetch_status == "done"
    assert page.quality_level is None
    assert (
        session.exec(select(PageMeta).where(PageMeta.page_pk == page.pk)).first()
        is None
    )


def test_refetch_updates_existing_page_meta(session):
    """A second fetch with new image data updates the PageMeta row in place
    rather than duplicating it."""
    title = "Page:Tractatus.djvu/47"
    remote = RemotePage(
        title=title,
        namespace_key=104,
        namespace_canonical="Page",
        content_model="proofread-page",
        text="page content",
        pageid=147,
        revid=1047,
    )

    def images(quality: int) -> RemotePageImages:
        return RemotePageImages(
            thumbnail_url=f"https://upload.example/thumb/q{quality}.jpg",
            fullsize_url=f"https://upload.example/full/q{quality}.jpg",
            quality=quality,
        )

    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)

    for quality in (1, 3):
        wiki = FakeWikiClient(
            pages={title: remote}, page_images={title: images(quality)}
        )
        session.add(FetchRequest(site_pk=site.pk, title=title))
        session.commit()
        assert run_pending(session, lambda _: wiki) == 1

    page = session.exec(select(Page).where(Page.title == title)).one()
    assert page.quality_level == 3
    metas = session.exec(
        select(PageMeta).where(PageMeta.page_pk == page.pk)
    ).all()
    assert len(metas) == 1
    assert metas[0].thumb_url == "https://upload.example/thumb/q3.jpg"


def test_page_model_has_raw_text_not_proofread_sections(session):
    text = (
        '<noinclude><pagequality level="1" user="Admin" />'
        '<div class="pagetext">Header</div></noinclude>'
        "Body"
        "<noinclude><div>Footer</div></noinclude>"
    )
    remote = RemotePage(
        title="Page:Tractatus.djvu/1",
        namespace_key=250,
        namespace_canonical="Page",
        content_model="proofread-page",
        text=text,
        pageid=101,
        revid=1001,
        sha1="b" * 40,
        size=len(text),
    )
    wiki = FakeWikiClient(pages={remote.title: remote})
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(FetchRequest(site_pk=site.pk, title=remote.title))
    session.commit()

    assert run_pending(session, lambda _: wiki) == 1
    page = session.exec(select(Page).where(Page.title == remote.title)).one()
    dumped = page.model_dump()
    assert dumped["text"] == text
    assert dumped["content_model"] == "proofread-page"
    assert "header" not in dumped
    assert "body" not in dumped
    assert "footer" not in dumped


def test_fetch_does_not_hold_db_lock_during_remote_get_page(engine):
    remote = _remote(
        "Page:Tractatus.djvu/1",
        "proofread-page",
        "Page",
        250,
        text="page content",
    )
    with Session(engine) as s:
        site = Site(family="mywikisource", code="en")
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(FetchRequest(site_pk=site.pk, title=remote.title))
        s.commit()

    def write_while_getting_page():
        with Session(engine) as s:
            s.add(Site(family="mywikisource", code="fr"))
            s.commit()

    wiki = GetPageHookClient(
        pages={remote.title: remote},
        on_get_page=write_while_getting_page,
    )

    with Session(engine) as s:
        assert run_pending(s, lambda _: wiki) == 1
        assert s.in_transaction() is False

    with Session(engine) as s:
        req = s.exec(
            select(FetchRequest).where(FetchRequest.title == remote.title)
        ).one()
        assert req.status == FetchStatus.done
        page = s.exec(select(Page).where(Page.title == remote.title)).one()
        assert page.text == "page content"


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


def test_index_fanout_fetches_subpages_without_pagelist(engine, tmp_path):
    """Index subpages are assets and do not depend on page-count detection."""
    index = _remote(_INDEX_TITLE, "proofread-index", "Index", 252)
    asset_title = f"{_INDEX_TITLE}/styles.css"
    wiki = FakeWikiClient(
        pages={
            _INDEX_TITLE: index,
            asset_title: _index_subpage_remote(asset_title),
        }
    )
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
    assert body["request"]["progress_total"] == 2
    with Session(engine) as s:
        assert {r.title for r in s.exec(select(FetchRequest)).all()} == {
            _INDEX_TITLE,
            asset_title,
        }
        assert {p.title for p in s.exec(select(Page)).all()} == {
            _INDEX_TITLE,
            asset_title,
        }


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
