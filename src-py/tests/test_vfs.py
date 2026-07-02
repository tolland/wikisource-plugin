"""Tests for the VFS read endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.api.schemas import WriteContentRequest
from wtbot.api.vfs import list_children, read_content, write_content
from wtbot.model import EditJournal, FileBlob, Page, Site
from wtbot.model.namespace import NsRole
from wtbot.vfs import WikisourceVfs

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
INDEX_STYLES = f"{INDEX}/styles.css"
FILE = "File:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
PAGE_1 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1"
PAGE_2 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/2"

_INDEX_BODY = "<pagelist to='2' />"
_FILE_BODY = "== Description ==\nA classic."
_PAGE_1_BODY = "{{recto}} Page one content."
_PAGE_2_BODY = "{{verso}} Page two content."

_INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"
_PAGES_PATH = f"{_INDEX_PATH}/Pages"
_FILE_PATH = f"{_INDEX_PATH}/{FILE}"


def _add_index_asset_tree(session: Session) -> None:
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(
        Page(
            site_pk=site.pk,
            title=INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
        )
    )
    session.add(
        Page(
            site_pk=site.pk,
            title=INDEX_STYLES,
            namespace_role=NsRole.index,
            content_model="sanitized-css",
            text=".pagetext {}",
            revid=5005,
            index_title=INDEX,
        )
    )
    session.commit()


@pytest.fixture
def vfs_client(engine, tmp_path) -> TestClient:
    """TestClient with a pre-populated cache: one index, two pages, one file blob."""
    from wtbot.main import create_app

    app = create_app(engine=engine, blob_root=tmp_path / "blobs")
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)

        index_page = Page(
            site_pk=site.pk,
            title=INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
            text=_INDEX_BODY,
            page_count=2,
            pageid=1001,
            revid=5001,
        )
        s.add(index_page)

        index_styles = Page(
            site_pk=site.pk,
            title=INDEX_STYLES,
            namespace_role=NsRole.index,
            content_model="sanitized-css",
            text=".pagetext {}",
            pageid=1005,
            revid=5005,
            index_title=INDEX,
        )
        s.add(index_styles)

        file_page = Page(
            site_pk=site.pk,
            title=FILE,
            namespace_role=NsRole.file,
            content_model="wikitext",
            text=_FILE_BODY,
            pageid=1002,
            revid=5002,
        )
        s.add(file_page)
        s.commit()
        s.refresh(file_page)

        blob = FileBlob(
            page_pk=file_page.pk,
            file_sha1="a" * 40,
            size=4_200_000,
            mime="image/vnd.djvu",
        )
        s.add(blob)

        p1 = Page(
            site_pk=site.pk,
            title=PAGE_1,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text=_PAGE_1_BODY,
            pageid=1003,
            revid=5003,
            index_title=INDEX,
            page_number=1,
        )
        p2 = Page(
            site_pk=site.pk,
            title=PAGE_2,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text=_PAGE_2_BODY,
            pageid=1004,
            revid=5004,
            index_title=INDEX,
            page_number=2,
        )
        s.add(p1)
        s.add(p2)
        s.commit()

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# stat
# ---------------------------------------------------------------------------


def test_stat_root(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": "/"})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_site(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"/{FAMILY}/{CODE}"})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_index(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _INDEX_PATH})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "directory"
    assert body["stable_id"] == 1001
    assert body["content_model"] == "proofread-index"


def test_stat_index_wikitext(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_INDEX_PATH}/wikitext"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "file"
    assert body["name"] == "wikitext"
    assert body["stable_id"] == 1001
    assert body["length"] == len(_INDEX_BODY.encode())
    assert body["content_model"] == "proofread-index"


def test_stat_pages_container(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _PAGES_PATH})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_page(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "file"
    assert body["stable_id"] == 1003
    assert body["length"] == len(_PAGE_1_BODY.encode())
    assert body["content_model"] == "proofread-page"


def test_stat_templates_stub(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_INDEX_PATH}/Templates"})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_transcluded_stub(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_INDEX_PATH}/TranscludedFiles"})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_file_dir(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _FILE_PATH})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_file_wikitext(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_FILE_PATH}/wikitext"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "file"
    assert body["length"] == len(_FILE_BODY.encode())
    assert body["content_model"] == "wikitext"


def test_stat_blob(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_FILE_PATH}/blob"})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "file"
    assert r.json()["length"] == 4_200_000


def test_stat_missing(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": "/wikisource/en/Index:NoSuch"})
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_stat_non_page_title_under_pages_is_missing(vfs_client):
    """A title that exists on the site but is not a Page: of this index must
    not resolve under the synthetic Pages/ container."""
    r = vfs_client.get("/vfs/stat", params={"path": f"{_PAGES_PATH}/{FILE}"})
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_stat_index_namespace_asset(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)

        stat = WikisourceVfs(s).stat(f"{_INDEX_PATH}/styles.css")

    assert stat.exists is True
    assert stat.name == "styles.css"
    assert stat.kind == "file"
    assert stat.revid == 5005
    assert stat.length == len(".pagetext {}".encode())
    assert stat.content_model == "sanitized-css"


# ---------------------------------------------------------------------------
# stat/bulk
# ---------------------------------------------------------------------------


def test_stat_bulk_matches_individual_stat(vfs_client):
    paths = [
        "/",
        _INDEX_PATH,
        f"{_INDEX_PATH}/wikitext",
        f"{_PAGES_PATH}/{PAGE_1}",
        f"{_PAGES_PATH}/{PAGE_2}",
        f"{_FILE_PATH}/wikitext",
        "/wikisource/en/Index:NoSuch",
        f"{_PAGES_PATH}/Page:NoSuchPage.djvu/1",
        f"{_PAGES_PATH}/{FILE}",
        "/wikisource/en/Index:NoSuch/Pages/Page:NoSuchPage.djvu/1",
    ]
    bulk = vfs_client.post("/vfs/stat/bulk", json={"paths": paths})
    assert bulk.status_code == 200
    results = bulk.json()["results"]
    assert len(results) == len(paths)

    for path, result in zip(paths, results):
        individual = vfs_client.get("/vfs/stat", params={"path": path}).json()
        assert result == individual, path


def test_stat_bulk_empty(vfs_client):
    r = vfs_client.post("/vfs/stat/bulk", json={"paths": []})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_stat_bulk_reflects_uncommitted_edit_length(vfs_client):
    """The batched EditJournal lookup in stat_bulk's Pages/ grouping must
    agree with the per-path fallback used everywhere else."""
    edited_body = "{{recto}} much longer edited content than before."
    w = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_PAGES_PATH}/{PAGE_1}",
            "content_base64": _b64(edited_body),
            "base_revid": 5003,
        },
    )
    assert w.json()["status"] == "ok"

    paths = [f"{_PAGES_PATH}/{PAGE_1}", f"{_PAGES_PATH}/{PAGE_2}"]
    bulk = vfs_client.post("/vfs/stat/bulk", json={"paths": paths})
    results = bulk.json()["results"]

    assert results[0]["length"] == len(edited_body.encode())
    assert results[0]["length"] != len(_PAGE_1_BODY.encode())
    assert results[1]["length"] == len(_PAGE_2_BODY.encode())

    for path, result in zip(paths, results):
        individual = vfs_client.get("/vfs/stat", params={"path": path}).json()
        assert result == individual, path


# ---------------------------------------------------------------------------
# list_children
# ---------------------------------------------------------------------------


def test_list_root(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": "/"})
    assert r.status_code == 200
    children = r.json()["children"]
    assert any(c["name"] == f"{FAMILY}/{CODE}" for c in children)
    assert all(c["kind"] == "directory" for c in children)


def test_list_site(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": f"/{FAMILY}/{CODE}"})
    assert r.status_code == 200
    children = r.json()["children"]
    assert len(children) == 1
    assert children[0]["name"] == INDEX
    assert children[0]["kind"] == "directory"
    assert INDEX_STYLES not in [c["name"] for c in children]


def test_list_site_excludes_index_namespace_assets(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)

        response = list_children(path=f"/{FAMILY}/{CODE}", session=s)

    assert [child.name for child in response.children] == [INDEX]


def test_list_index_includes_index_namespace_assets(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)
        site = s.exec(
            select(Site).where(Site.family == FAMILY, Site.code == CODE)
        ).one()
        s.add(
            Page(
                site_pk=site.pk,
                title=f"{INDEX}/legacy.css",
                namespace_role=NsRole.index,
                content_model="sanitized-css",
                text=".legacy {}",
            )
        )
        s.commit()

        response = list_children(path=_INDEX_PATH, session=s)

    by_name = {child.name: child for child in response.children}
    assert by_name["styles.css"].kind == "file"
    assert by_name["styles.css"].content_model == "sanitized-css"
    assert by_name["legacy.css"].kind == "file"


def test_list_index_has_containers(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _INDEX_PATH})
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["children"]]
    assert "wikitext" in names
    assert "Pages" in names
    assert FILE in names
    assert "Templates" in names
    assert "TranscludedFiles" in names
    assert "styles.css" in names
    # no Page: titles directly under index
    assert PAGE_1 not in names
    assert PAGE_2 not in names
    kinds = {c["name"]: c["kind"] for c in r.json()["children"]}
    assert kinds["wikitext"] == "file"
    assert kinds["Pages"] == "directory"
    assert kinds[FILE] == "directory"
    assert kinds["styles.css"] == "file"
    assert kinds["Templates"] == "directory"
    assert kinds["TranscludedFiles"] == "directory"


def test_list_index_wikitext_matches_stat(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _INDEX_PATH})
    node = next(c for c in r.json()["children"] if c["name"] == "wikitext")
    stat = vfs_client.get(
        "/vfs/stat", params={"path": f"{_INDEX_PATH}/wikitext"}
    ).json()
    assert node["path"] == stat["path"]
    assert node["stable_id"] == stat["stable_id"]
    assert node["revid"] == stat["revid"]
    assert node["length"] == stat["length"]
    assert node["content_model"] == stat["content_model"]


def test_list_pages_container(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _PAGES_PATH})
    assert r.status_code == 200
    children = r.json()["children"]
    names = [c["name"] for c in children]
    assert PAGE_1 in names
    assert PAGE_2 in names
    assert all(c["kind"] == "file" for c in children)
    assert all(c["content_model"] == "proofread-page" for c in children)


def test_list_pages_sorted(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _PAGES_PATH})
    children = r.json()["children"]
    assert children[0]["name"] == PAGE_1
    assert children[1]["name"] == PAGE_2


def test_list_templates_stub_empty(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": f"{_INDEX_PATH}/Templates"})
    assert r.status_code == 200
    assert r.json()["children"] == []


def test_list_transcluded_stub_empty(vfs_client):
    r = vfs_client.get(
        "/vfs/children", params={"path": f"{_INDEX_PATH}/TranscludedFiles"}
    )
    assert r.status_code == 200
    assert r.json()["children"] == []


def test_list_file_dir(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _FILE_PATH})
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["children"]]
    assert "wikitext" in names
    assert "blob" in names
    assert len(r.json()["children"]) == 2


# ---------------------------------------------------------------------------
# read_content
# ---------------------------------------------------------------------------


def test_read_page(vfs_client):
    import base64

    r = vfs_client.get("/vfs/content", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert r.status_code == 200
    body = r.json()
    assert body["revid"] == 5003
    assert "content_model" not in body
    assert base64.b64decode(body["content_base64"]).decode() == _PAGE_1_BODY


def test_read_file_wikitext(vfs_client):
    """Must serve the File: page's own description body — matching what
    stat() reports for the same path (and what write() targets) — not the
    parent Index body."""
    import base64

    r = vfs_client.get("/vfs/content", params={"path": f"{_FILE_PATH}/wikitext"})
    assert r.status_code == 200
    assert base64.b64decode(r.json()["content_base64"]).decode() == _FILE_BODY


def test_read_blob_returns_501(vfs_client):
    r = vfs_client.get("/vfs/content", params={"path": f"{_FILE_PATH}/blob"})
    assert r.status_code == 501


def test_read_missing_page_returns_404(vfs_client):
    r = vfs_client.get("/vfs/content", params={"path": f"{_PAGES_PATH}/Page:NoSuch/99"})
    assert r.status_code == 404


def test_read_index_namespace_asset(engine):
    import base64

    with Session(engine) as s:
        _add_index_asset_tree(s)

        response = read_content(path=f"{_INDEX_PATH}/styles.css", session=s)

    assert response.revid == 5005
    assert base64.b64decode(response.content_base64).decode() == ".pagetext {}"


# ---------------------------------------------------------------------------
# write_content
# ---------------------------------------------------------------------------


def _b64(s: str) -> str:
    import base64

    return base64.b64encode(s.encode()).decode()


def _unb64(s: str) -> str:
    import base64

    return base64.b64decode(s).decode()


def test_write_page_ok(vfs_client, engine):
    new_body = "{{recto}} Edited page one content."
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_PAGES_PATH}/{PAGE_1}",
            "content_base64": _b64(new_body),
            "base_revid": 5003,
            "comment": "fix typo",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"

    with Session(engine) as s:
        page = s.exec(select(Page).where(Page.title == PAGE_1)).first()
        # Page.text is the cached *remote* body -- a local save must never
        # touch it, or a later refresh loses the diff base.
        assert page.text == _PAGE_1_BODY
        assert page.dirty is True

        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).first()
        assert journal is not None
        assert journal.body == new_body
        assert journal.base_revid == 5003
        assert journal.committed is False

    # read_content/stat serve the uncommitted journal body, not Page.text.
    r = vfs_client.get("/vfs/content", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert _unb64(r.json()["content_base64"]) == new_body

    r = vfs_client.get("/vfs/stat", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert r.json()["length"] == len(new_body.encode())


def test_write_page_conflict(vfs_client):
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_PAGES_PATH}/{PAGE_1}",
            "content_base64": _b64("stale edit"),
            "base_revid": 1,  # stale -- real revid is 5003
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "conflict"
    assert body["new_revid"] == 5003


def test_write_blob_returns_error_status(vfs_client):
    """The binary blob leaf is not a wikitext page; a write must be refused
    rather than silently journalled against the File: description page."""
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_FILE_PATH}/blob",
            "content_base64": _b64("x"),
            "base_revid": None,
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_write_missing_page_returns_error_status(vfs_client):
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_PAGES_PATH}/Page:NoSuch/99",
            "content_base64": _b64("x"),
            "base_revid": None,
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_write_index_namespace_asset(engine):
    new_body = ".pagetext { color: red; }"
    with Session(engine) as s:
        _add_index_asset_tree(s)

        result = write_content(
            WriteContentRequest(
                path=f"{_INDEX_PATH}/styles.css",
                content_base64=_b64(new_body),
                base_revid=5005,
                comment="adjust styles",
            ),
            session=s,
        )

        page = s.exec(select(Page).where(Page.title == INDEX_STYLES)).one()
        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).one()

    assert result.status == "ok"
    assert page.text == ".pagetext {}"  # unchanged -- still the cached remote body
    assert page.dirty is True
    assert journal.body == new_body
    assert journal.base_revid == 5005

    with Session(engine) as s:
        content = read_content(f"{_INDEX_PATH}/styles.css", session=s)
    assert _unb64(content.content_base64) == new_body


def test_write_twice_read_content_serves_latest_journal(vfs_client):
    """Multiple saves before a commit -- read_content must serve the most
    recent one, not the first."""
    first = "{{recto}} first edit."
    second = "{{recto}} second edit."
    for body in (first, second):
        r = vfs_client.post(
            "/vfs/content",
            json={
                "path": f"{_PAGES_PATH}/{PAGE_1}",
                "content_base64": _b64(body),
                "base_revid": 5003,
            },
        )
        assert r.json()["status"] == "ok"

    r = vfs_client.get("/vfs/content", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert _unb64(r.json()["content_base64"]) == second


def test_read_content_falls_back_to_page_text_once_journal_is_committed(
    vfs_client, engine
):
    """Once the commit worker marks a journal committed (and, per its own
    contract, the fetch worker has refreshed Page.text with the pushed
    body), read_content must go back to serving Page.text -- a committed
    journal is history, not the live edit."""
    edited_body = "{{recto}} pushed to the wiki now."
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": f"{_PAGES_PATH}/{PAGE_1}",
            "content_base64": _b64(edited_body),
            "base_revid": 5003,
        },
    )
    assert r.json()["status"] == "ok"

    with Session(engine) as s:
        page = s.exec(select(Page).where(Page.title == PAGE_1)).one()
        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).one()
        journal.committed = True
        s.add(journal)
        # Simulates the fetch worker's post-push refresh.
        page.text = edited_body
        s.add(page)
        s.commit()

    r = vfs_client.get("/vfs/content", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert _unb64(r.json()["content_base64"]) == edited_body
