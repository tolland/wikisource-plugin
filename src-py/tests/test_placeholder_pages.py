import base64

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import EditJournal, FetchRequest, FetchStatus, Page, Site
from wtbot.model.page_meta import PageMeta
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import IndexPageEntry, RemotePage
from wtbot.worker import run_pending

"""Partially transcribed works: fan-out discovers the index pagination via
list=proofreadpagesinindex, creates local placeholder stub rows for pages
that do not exist on the wiki yet (pageid/revid None — the provisional-Page
shape), and only enqueues fetches for pages that do. The VFS then lists,
stats, opens (with a scaffold body) and edits placeholders like any other
page; committing a placeholder's journal creates the page remotely."""

FAMILY = "mywikisource"
CODE = "en"
INDEX = "Index:Sparse.pdf"
FILE = "File:Sparse.pdf"
PAGE_5 = "Page:Sparse.pdf/5"

_INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"
_PAGES_PATH = f"{_INDEX_PATH}/Pages"

_INDEX_BODY = "<pagelist />"
_PAGE_5_BODY = "{{c|REPORT}} Page five, the only transcribed one."

_ENTRIES = [
    IndexPageEntry(page_offset=n, title=f"Page:Sparse.pdf/{n}", pageid=None)
    for n in range(1, 5)
] + [IndexPageEntry(page_offset=5, title=PAGE_5, pageid=11605)]


def _remote(
    title: str, cm: str, ns: str, key: int, text: str, revid: int
) -> RemotePage:
    return RemotePage(
        title=title,
        namespace_key=key,
        namespace_canonical=ns,
        content_model=cm,
        text=text,
        pageid=revid + 1000,
        revid=revid,
    )


def _fake_wiki() -> FakeWikiClient:
    return FakeWikiClient(
        pages={
            INDEX: _remote(INDEX, "proofread-index", "Index", 252, _INDEX_BODY, 100),
            PAGE_5: _remote(PAGE_5, "proofread-page", "Page", 250, _PAGE_5_BODY, 105),
        },
        files={FILE: b"%PDF-fake"},
        index_pages={INDEX: _ENTRIES},
    )


def _seed_and_fan_out(engine, tmp_path) -> FakeWikiClient:
    wiki = _fake_wiki()
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(FetchRequest(site_pk=site.pk, title=INDEX, depth=1))
        s.commit()
        run_pending(s, lambda _: wiki, blob_root=tmp_path / "blobs")
    return wiki


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _unb64(s: str) -> str:
    return base64.b64decode(s).decode()


# -- fan-out ---------------------------------------------------------------------


def test_fanout_creates_stubs_and_fetches_only_existing(engine, tmp_path):
    _seed_and_fan_out(engine, tmp_path)
    with Session(engine) as s:
        rows = s.exec(
            select(Page, PageMeta)
            .join(PageMeta, PageMeta.page_pk == Page.pk)
            .where(PageMeta.index_title == INDEX)
            .order_by(PageMeta.page_number)
        ).all()
        pages = [page for page, _ in rows]
        assert [meta.page_number for _, meta in rows] == [1, 2, 3, 4, 5]
        stubs = [(page, meta) for page, meta in rows if page.revid is None]
        assert [meta.page_number for _, meta in stubs] == [1, 2, 3, 4]
        for stub, _ in stubs:
            assert stub.pageid is None
            assert stub.text is None
            assert stub.content_model == "proofread-page"
            assert stub.dirty is False

        # Page 5 was fetched for real.
        page5 = next(page for page, meta in rows if meta.page_number == 5)
        assert page5.revid == 105
        assert page5.text == _PAGE_5_BODY

        # No fetch requests were wasted on known-missing pages.
        child_titles = [
            r.title
            for r in s.exec(
                select(FetchRequest).where(FetchRequest.parent_pk.is_not(None))
            ).all()
        ]
        assert child_titles == [PAGE_5]

        # The parent request completed (1 index + 1 child).
        parent = s.exec(
            select(FetchRequest).where(FetchRequest.parent_pk.is_(None))
        ).one()
        assert parent.status == FetchStatus.done
        assert parent.progress_total == 2
        # page_count derived from the pagination when <pagelist> is bare.
        index_row = s.exec(select(Page).where(Page.title == INDEX)).one()
        assert index_row.page_count == 5


def test_refanout_does_not_clobber_edited_stub(engine, tmp_path):
    wiki = _seed_and_fan_out(engine, tmp_path)
    with Session(engine) as s:
        stub = s.exec(select(Page).where(Page.title == "Page:Sparse.pdf/2")).one()
        s.add(EditJournal(page_pk=stub.pk, base_revid=None, body="typed text"))
        stub.dirty = True
        s.add(stub)
        s.commit()
        stub_pk = stub.pk

        s.add(FetchRequest(site_pk=stub.site_pk, title=INDEX, depth=1))
        s.commit()
        run_pending(s, lambda _: wiki, blob_root=tmp_path / "blobs")

        again = s.exec(select(Page).where(Page.title == "Page:Sparse.pdf/2")).one()
        assert again.pk == stub_pk
        assert again.dirty is True
        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == stub_pk)
        ).one()
        assert journal.body == "typed text"


# -- VFS surface -----------------------------------------------------------------


def _client(engine, tmp_path) -> TestClient:
    app = create_app(engine=engine, blob_root=tmp_path / "blobs")
    return TestClient(app)


def test_placeholders_listed_with_flag(engine, tmp_path):
    _seed_and_fan_out(engine, tmp_path)
    with _client(engine, tmp_path) as c:
        children = c.get("/vfs/children", params={"path": _PAGES_PATH}).json()[
            "children"
        ]
        by_number = {c_["name"]: c_ for c_ in children}
        assert len(children) == 5
        assert by_number["Page:Sparse.pdf/1"]["placeholder"] is True
        assert by_number["Page:Sparse.pdf/1"]["writable"] is True
        assert by_number[PAGE_5]["placeholder"] is False

        stat = c.get(
            "/vfs/stat", params={"path": f"{_PAGES_PATH}/Page:Sparse.pdf/3"}
        ).json()
        assert stat["exists"] is True
        assert stat["placeholder"] is True

        # Bulk and individual stat agree on placeholders too.
        paths = [f"{_PAGES_PATH}/Page:Sparse.pdf/3", f"{_PAGES_PATH}/{PAGE_5}"]
        bulk = c.post("/vfs/stat/bulk", json={"paths": paths}).json()["results"]
        for path, result in zip(paths, bulk):
            assert result == c.get("/vfs/stat", params={"path": path}).json(), path


def test_placeholder_opens_with_scaffold_and_saves_as_edit(engine, tmp_path):
    _seed_and_fan_out(engine, tmp_path)
    path = f"{_PAGES_PATH}/Page:Sparse.pdf/1"
    with _client(engine, tmp_path) as c:
        r = c.get("/vfs/content", params={"path": path}).json()
        body = _unb64(r["content_base64"])
        assert '<pagequality level="1"' in body
        assert r["revid"] is None

        transcription = body.replace("\n\n", "\nFirst transcribed line.\n", 1)
        w = c.post(
            "/vfs/content",
            json={"path": path, "content_base64": _b64(transcription)},
        )
        assert w.json()["status"] == "ok"

        # The save is journalled and takes precedence over the scaffold.
        r = c.get("/vfs/content", params={"path": path}).json()
        assert _unb64(r["content_base64"]) == transcription
        stat = c.get("/vfs/stat", params={"path": path}).json()
        assert stat["dirty"] is True
        assert stat["placeholder"] is True  # still not on the wiki


def test_committing_placeholder_creates_remote_page(engine, tmp_path):
    wiki = _seed_and_fan_out(engine, tmp_path)
    path = f"{_PAGES_PATH}/Page:Sparse.pdf/4"
    app = create_app(
        engine=engine, blob_root=tmp_path / "blobs", client_factory=lambda site: wiki
    )
    with TestClient(app) as c:
        w = c.post(
            "/vfs/content",
            json={"path": path, "content_base64": _b64("fresh transcription")},
        )
        assert w.json()["status"] == "ok"

        resp = c.post("/commits/")
        assert resp.status_code == 200

    # The page now exists on the (fake) wiki...
    created = wiki.get_page("Page:Sparse.pdf/4")
    assert created.text == "fresh transcription"

    # ...and the local row is no longer a placeholder.
    with Session(engine) as s:
        page = s.exec(select(Page).where(Page.title == "Page:Sparse.pdf/4")).one()
        assert page.revid is not None
        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).one()
        assert journal.committed is True
