"""Tests for the VFS read endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from wtbot.sqlmodel import FileBlob, Page, Site
from wtbot.sqlmodel.namespace import NsRole

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
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
            site_pk=site.pk, title=INDEX,
            namespace_role=NsRole.index, content_model="proofread-index",
            text=_INDEX_BODY, page_count=2, pageid=1001, revid=5001,
        )
        s.add(index_page)

        file_page = Page(
            site_pk=site.pk, title=FILE,
            namespace_role=NsRole.file, content_model="wikitext",
            text=_FILE_BODY, pageid=1002, revid=5002,
        )
        s.add(file_page)
        s.commit()
        s.refresh(file_page)

        blob = FileBlob(
            page_pk=file_page.pk, file_sha1="a" * 40,
            size=4_200_000, mime="image/vnd.djvu",
        )
        s.add(blob)

        p1 = Page(
            site_pk=site.pk, title=PAGE_1,
            namespace_role=NsRole.page, content_model="proofread-page",
            text=_PAGE_1_BODY, pageid=1003, revid=5003,
            index_title=INDEX, page_number=1,
        )
        p2 = Page(
            site_pk=site.pk, title=PAGE_2,
            namespace_role=NsRole.page, content_model="proofread-page",
            text=_PAGE_2_BODY, pageid=1004, revid=5004,
            index_title=INDEX, page_number=2,
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


def test_list_index_has_containers(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _INDEX_PATH})
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["children"]]
    assert "Pages" in names
    assert FILE in names
    assert "Templates" in names
    assert "TranscludedFiles" in names
    # no Page: titles directly under index
    assert PAGE_1 not in names
    assert PAGE_2 not in names
    kinds = {c["name"]: c["kind"] for c in r.json()["children"]}
    assert kinds["Pages"] == "directory"
    assert kinds[FILE] == "directory"
    assert kinds["Templates"] == "directory"
    assert kinds["TranscludedFiles"] == "directory"


def test_list_pages_container(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _PAGES_PATH})
    assert r.status_code == 200
    children = r.json()["children"]
    names = [c["name"] for c in children]
    assert PAGE_1 in names
    assert PAGE_2 in names
    assert all(c["kind"] == "file" for c in children)


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
    r = vfs_client.get("/vfs/children",
                       params={"path": f"{_INDEX_PATH}/TranscludedFiles"})
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
    r = vfs_client.get("/vfs/content",
                       params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert r.status_code == 200
    body = r.json()
    assert body["revid"] == 5003
    assert base64.b64decode(body["content_base64"]).decode() == _PAGE_1_BODY


def test_read_file_wikitext(vfs_client):
    import base64
    r = vfs_client.get("/vfs/content",
                       params={"path": f"{_FILE_PATH}/wikitext"})
    assert r.status_code == 200
    assert base64.b64decode(r.json()["content_base64"]).decode() == _FILE_BODY


def test_read_blob_returns_501(vfs_client):
    r = vfs_client.get("/vfs/content", params={"path": f"{_FILE_PATH}/blob"})
    assert r.status_code == 501


def test_read_missing_page_returns_404(vfs_client):
    r = vfs_client.get("/vfs/content",
                       params={"path": f"{_PAGES_PATH}/Page:NoSuch/99"})
    assert r.status_code == 404
