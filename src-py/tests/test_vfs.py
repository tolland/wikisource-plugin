"""Tests for the VFS read endpoints."""

from __future__ import annotations

import base64
import json

import pytest
from conftest import add_proofread_meta, make_page
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from wtbot.api.schemas import WriteContentRequest
from wtbot.api.vfs import list_children, read_content, write_content
from wtbot.model import EditJournal, FileBlob, Page, Site, Title
from wtbot.model.wiki.namespace import Namespace
from wtbot.vfs import WikisourceVfs
from wtbot.vfs.namespaces import SiteNamespaces

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

_NAMESPACES = SiteNamespaces.from_rows([])


def _node(title: str) -> str:
    return _NAMESPACES.node_path(FAMILY, CODE, title)


def _wikitext(title: str) -> str:
    return _NAMESPACES.node_path(FAMILY, CODE, title, aspect="wikitext")


_INDEX_PATH = _node(INDEX)
_SITE_PATH = f"/{FAMILY}/{CODE}"
_PAGES_PATH = f"{_INDEX_PATH}/@pages"
_STYLES_PATH = f"{_INDEX_PATH}/styles.css"


def _add_index_asset_tree(session: Session) -> None:
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(
        make_page(
            site_pk=site.pk,
            title=INDEX,
            content_model="proofread-index",
        )
    )
    styles = make_page(
        site_pk=site.pk,
        title=INDEX_STYLES,
        content_model="sanitized-css",
        text=".pagetext {}",
        revid=5005,
    )
    session.add(styles)
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

        index_page = make_page(
            site_pk=site.pk,
            title=INDEX,
            content_model="proofread-index",
            text=_INDEX_BODY,
            pageid=1001,
            revid=5001,
        )
        s.add(index_page)

        index_styles = make_page(
            site_pk=site.pk,
            title=INDEX_STYLES,
            content_model="sanitized-css",
            text=".pagetext {}",
            pageid=1005,
            revid=5005,
        )
        s.add(index_styles)
        file_page = make_page(
            site_pk=site.pk,
            title=FILE,
            content_model="wikitext",
            text=_FILE_BODY,
            pageid=1002,
            revid=5002,
        )
        s.add(file_page)
        s.commit()
        s.refresh(file_page)
        file_page.address.namespace_key = 6

        blob = FileBlob(
            page_pk=file_page.pk,
            file_sha1="a" * 40,
            size=4_200_000,
            mime="image/vnd.djvu",
        )
        s.add(blob)

        p1 = make_page(
            site_pk=site.pk,
            title=PAGE_1,
            content_model="proofread-page",
            text=_PAGE_1_BODY,
            pageid=1003,
            revid=5003,
        )
        p2 = make_page(
            site_pk=site.pk,
            title=PAGE_2,
            content_model="proofread-page",
            text=_PAGE_2_BODY,
            pageid=1004,
            revid=5004,
        )
        s.add(p1)
        s.add(p2)
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        add_proofread_meta(
            s,
            page_pk=p1.pk,
            index_title=INDEX,
            page_number=1,
            quality_level=1,
            thumb_url="https://ws.example/thumb/page1-240px.jpg",
            source_image_url="https://ws.example/thumb/page1-2419px.jpg",
            thumb_width=240,
        )
        add_proofread_meta(s, page_pk=p2.pk, index_title=INDEX, page_number=2)
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
    r = vfs_client.get("/vfs/stat", params={"path": f"{_INDEX_PATH}/@wikitext"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "file"
    assert body["name"] == "@wikitext"
    assert body["stable_id"] == 1001
    assert body["length"] == len(_INDEX_BODY.encode())
    assert body["content_model"] == "proofread-index"


def test_stat_pages_container(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _PAGES_PATH})
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["kind"] == "directory"


def test_stat_page(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _wikitext(PAGE_1)})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["kind"] == "file"
    assert body["stable_id"] == 1003
    assert body["length"] == len(_PAGE_1_BODY.encode())
    assert body["content_model"] == "proofread-page"


def test_stat_missing(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": _node("Index:NoSuch")})
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_stat_carries_decoration_fields(vfs_client):
    """quality_level / dirty / has_reference_image ride on stat so the tree can
    colour-code without extra round trips."""
    r = vfs_client.get("/vfs/stat", params={"path": _wikitext(PAGE_1)}).json()
    assert r["quality_level"] == 1
    assert r["dirty"] is False
    assert r["has_reference_image"] is True

    # No ProofreadPageMeta row for page 2 -- no scan image known (yet).
    r = vfs_client.get("/vfs/stat", params={"path": _wikitext(PAGE_2)}).json()
    assert r["quality_level"] is None
    assert r["has_reference_image"] is False


def test_children_carry_decoration_fields(vfs_client):
    children = vfs_client.get("/vfs/children", params={"path": _PAGES_PATH}).json()[
        "children"
    ]
    by_path = {c["path"]: c for c in children}
    assert by_path[_node(PAGE_1)]["quality_level"] == 1
    assert by_path[_node(PAGE_1)]["has_reference_image"] is True
    assert by_path[_node(PAGE_2)]["has_reference_image"] is False


def test_stat_reports_dirty_after_local_save(vfs_client):
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": _wikitext(PAGE_1),
            "content_base64": _b64("edited for dirty check"),
            "base_revid": 5003,
        },
    )
    assert r.json()["status"] == "ok"
    assert (
        vfs_client.get("/vfs/stat", params={"path": _wikitext(PAGE_1)}).json()["dirty"]
        is True
    )


def test_stat_any_cached_title_resolves(vfs_client):
    """Every title the cache holds is a node, whatever its namespace."""
    r = vfs_client.get("/vfs/stat", params={"path": _node(FILE)}).json()
    assert r["exists"] is True
    assert r["kind"] == "directory"
    assert r["aspects"] == ["wikitext", "props"]
    r = vfs_client.get("/vfs/stat", params={"path": _wikitext(FILE)}).json()
    assert r["exists"] is True
    assert r["kind"] == "file"
    assert r["content_model"] == "wikitext"


def test_stat_index_namespace_asset(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)

        stat = WikisourceVfs(s).stat(f"{_STYLES_PATH}/@wikitext")

    assert stat.exists is True
    assert stat.name == "@wikitext"
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
        f"{_INDEX_PATH}/@wikitext",
        _wikitext(PAGE_1),
        _wikitext(PAGE_2),
        _node("Index:NoSuch"),
        _wikitext("Page:NoSuchPage.djvu/1"),
        _wikitext(FILE),
        _node("Page:NoSuchPage.djvu/1"),
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
            "path": _wikitext(PAGE_1),
            "content_base64": _b64(edited_body),
            "base_revid": 5003,
        },
    )
    assert w.json()["status"] == "ok"

    paths = [_wikitext(PAGE_1), _wikitext(PAGE_2)]
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
    # namespaces holding titles; Page is browsed through its Index instead
    assert [c["name"] for c in children] == ["File", "Index"]
    assert all(c["kind"] == "directory" for c in children)


def test_list_namespace_has_top_level_titles_only(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": f"{_SITE_PATH}/Index"})
    children = r.json()["children"]
    # the styles.css subpage is below the index, not beside it
    assert [c["path"] for c in children] == [_INDEX_PATH]
    assert children[0]["has_children"] is True
    assert children[0]["aspects"] == ["wikitext", "props", "pages"]


def test_list_page_namespace_is_addressable_but_unlisted(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": f"{_SITE_PATH}/Page"})
    paths = [c["path"] for c in r.json()["children"]]
    assert paths == [_node(PAGE_1), _node(PAGE_2)]


def test_list_site_excludes_index_namespace_assets(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)

        response = list_children(path=f"/{FAMILY}/{CODE}", session=s)

    assert [child.name for child in response.children] == ["Index"]

    with Session(engine) as s:
        response = list_children(path=f"/{FAMILY}/{CODE}/Index", session=s)
    assert [child.path for child in response.children] == [_INDEX_PATH]


def test_list_index_includes_index_namespace_assets(engine):
    with Session(engine) as s:
        _add_index_asset_tree(s)
        site = s.exec(
            select(Site).where(Site.family == FAMILY, Site.code == CODE)
        ).one()
        s.add(
            make_page(
                site_pk=site.pk,
                title=f"{INDEX}/legacy.css",
                content_model="sanitized-css",
                text=".legacy {}",
            )
        )
        s.commit()

        response = list_children(path=_INDEX_PATH, session=s)

    by_name = {child.name: child for child in response.children}
    assert by_name["styles.css"].kind == "directory"
    assert by_name["styles.css"].content_model == "sanitized-css"
    assert by_name["styles.css"].aspects == ["wikitext", "props"]
    assert by_name["legacy.css"].kind == "directory"


def test_list_index_has_containers(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _INDEX_PATH})
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["children"]]
    assert "@wikitext" in names
    assert "@props" in names
    assert "@pages" in names
    # the backing File: is not part of the plugin-facing tree
    assert FILE not in names
    assert "Templates" not in names
    assert "TranscludedFiles" not in names
    assert "styles.css" in names
    # no Page: titles directly under index
    assert PAGE_1 not in names
    assert PAGE_2 not in names
    kinds = {c["name"]: c["kind"] for c in r.json()["children"]}
    assert kinds["@wikitext"] == "file"
    assert kinds["@props"] == "file"
    assert kinds["@pages"] == "directory"
    assert kinds["styles.css"] == "directory"


def test_list_index_wikitext_matches_stat(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _INDEX_PATH})
    node = next(c for c in r.json()["children"] if c["name"] == "@wikitext")
    stat = vfs_client.get(
        "/vfs/stat", params={"path": f"{_INDEX_PATH}/@wikitext"}
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
    assert [c["name"] for c in children] == ["1", "2"]
    assert all(c["kind"] == "directory" for c in children)
    assert all(c["content_model"] == "proofread-page" for c in children)
    assert all(c["aspects"] == ["wikitext", "props"] for c in children)
    # a page's path is its own title in the Page namespace, not nested under
    # the index that lists it
    assert [c["path"] for c in children] == [_node(PAGE_1), _node(PAGE_2)]


def test_legacy_nested_page_path_is_missing(vfs_client):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_PAGES_PATH}/{PAGE_1}"})
    assert r.json()["exists"] is False


def test_list_pages_sorted(vfs_client):
    r = vfs_client.get("/vfs/children", params={"path": _PAGES_PATH})
    children = r.json()["children"]
    assert children[0]["path"] == _node(PAGE_1)
    assert children[1]["path"] == _node(PAGE_2)


# ---------------------------------------------------------------------------
# read_content
# ---------------------------------------------------------------------------


def test_read_page(vfs_client):
    import base64

    r = vfs_client.get("/vfs/content", params={"path": _wikitext(PAGE_1)})
    assert r.status_code == 200
    body = r.json()
    assert body["revid"] == 5003
    assert "content_model" not in body
    assert base64.b64decode(body["content_base64"]).decode() == _PAGE_1_BODY


def test_read_missing_page_returns_404(vfs_client):
    r = vfs_client.get("/vfs/content", params={"path": _wikitext("Page:NoSuch/99")})
    assert r.status_code == 404


def test_read_index_namespace_asset(engine):
    import base64

    with Session(engine) as s:
        _add_index_asset_tree(s)

        response = read_content(path=f"{_STYLES_PATH}/@wikitext", session=s)

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
            "path": _wikitext(PAGE_1),
            "content_base64": _b64(new_body),
            "base_revid": 5003,
            "comment": "fix typo",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"

    with Session(engine) as s:
        page = s.exec(
            select(Page)
            .join(Title, col(Title.pk) == col(Page.pk))
            .where(Title.title == PAGE_1)
        ).first()
        # Page.text is the cached *remote* body -- a local save must never
        # touch it, or a later refresh loses the diff base.
        assert page.text == _PAGE_1_BODY
        assert page.address.dirty is True

        journal = s.exec(
            select(EditJournal).where(EditJournal.title_pk == page.pk)
        ).first()
        assert journal is not None
        assert journal.body == new_body
        assert journal.base_revid == 5003
        assert journal.committed is False

    # read_content/stat serve the uncommitted journal body, not Page.text.
    r = vfs_client.get("/vfs/content", params={"path": _wikitext(PAGE_1)})
    assert _unb64(r.json()["content_base64"]) == new_body

    r = vfs_client.get("/vfs/stat", params={"path": _wikitext(PAGE_1)})
    assert r.json()["length"] == len(new_body.encode())


def test_write_page_conflict(vfs_client):
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": _wikitext(PAGE_1),
            "content_base64": _b64("stale edit"),
            "base_revid": 1,  # stale -- real revid is 5003
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "conflict"
    assert body["new_revid"] == 5003


def test_write_missing_page_returns_error_status(vfs_client):
    r = vfs_client.post(
        "/vfs/content",
        json={
            "path": _wikitext("Page:NoSuch/99"),
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
                path=f"{_STYLES_PATH}/@wikitext",
                content_base64=_b64(new_body),
                base_revid=5005,
                comment="adjust styles",
            ),
            session=s,
        )

        page = s.exec(
            select(Page)
            .join(Title, col(Title.pk) == col(Page.pk))
            .where(Title.title == INDEX_STYLES)
        ).one()
        journal = s.exec(
            select(EditJournal).where(EditJournal.title_pk == page.pk)
        ).one()

    assert result.status == "ok"
    assert page.text == ".pagetext {}"  # unchanged -- still the cached remote body
    assert page.address.dirty is True
    assert journal.body == new_body
    assert journal.base_revid == 5005

    with Session(engine) as s:
        content = read_content(f"{_STYLES_PATH}/@wikitext", session=s)
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
                "path": _wikitext(PAGE_1),
                "content_base64": _b64(body),
                "base_revid": 5003,
            },
        )
        assert r.json()["status"] == "ok"

    r = vfs_client.get("/vfs/content", params={"path": _wikitext(PAGE_1)})
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
            "path": _wikitext(PAGE_1),
            "content_base64": _b64(edited_body),
            "base_revid": 5003,
        },
    )
    assert r.json()["status"] == "ok"

    with Session(engine) as s:
        page = s.exec(
            select(Page)
            .join(Title, col(Title.pk) == col(Page.pk))
            .where(Title.title == PAGE_1)
        ).one()
        journal = s.exec(
            select(EditJournal).where(EditJournal.title_pk == page.pk)
        ).one()
        journal.committed = True
        s.add(journal)
        # Simulates the fetch worker's post-push refresh.
        page.text = edited_body
        s.add(page)
        s.commit()

    r = vfs_client.get("/vfs/content", params={"path": _wikitext(PAGE_1)})
    assert _unb64(r.json()["content_base64"]) == edited_body


@pytest.mark.parametrize(
    "suffix",
    ["Templates", "TranscludedFiles", FILE, f"{FILE}/wikitext", f"{FILE}/blob"],
)
def test_removed_virtual_nodes_are_missing(vfs_client, suffix):
    r = vfs_client.get("/vfs/stat", params={"path": f"{_INDEX_PATH}/{suffix}"})
    assert r.status_code == 200
    assert r.json()["exists"] is False


# ---------------------------------------------------------------------------
# generic title tree: any namespace, subpages, synthetic nodes, aspects
# ---------------------------------------------------------------------------

BOOK = "Book:Virtues and vices"
_BOOK_NAMESPACES = SiteNamespaces.from_rows(
    [
        Namespace(
            site_pk=0, key=3000, canonical_name="Book", local_name="Book", subpages=True
        )
    ]
)


def _book_node(title: str) -> str:
    return _BOOK_NAMESPACES.node_path(FAMILY, CODE, title)


def _book_wikitext(title: str) -> str:
    return _BOOK_NAMESPACES.node_path(FAMILY, CODE, title, aspect="wikitext")


@pytest.fixture
def book_client(engine, tmp_path) -> TestClient:
    """A `Book:` work -- a page with subpages, one level of them synthetic."""
    from wtbot.main import create_app

    app = create_app(engine=engine, blob_root=tmp_path / "blobs")
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(
            Namespace(
                site_pk=site.pk,
                key=3000,
                canonical_name="Book",
                local_name="Book",
                subpages=True,
            )
        )
        for title, body in (
            (BOOK, "{{book}}"),
            (f"{BOOK}/Chapter 1", "one"),
            (f"{BOOK}/Chapter 10", "ten"),
            (f"{BOOK}/Chapter 2", "two"),
            (f"{BOOK}/Part 2/Section 3", "deep"),
        ):
            s.add(make_page(site_pk=site.pk, title=title, text=body, revid=7))
        s.commit()
    with TestClient(app) as c:
        yield c


def _children(client: TestClient, path: str) -> list[dict]:
    r = client.get("/vfs/children", params={"path": path})
    assert r.status_code == 200
    return r.json()["children"]


def test_book_is_listed_under_its_namespace(book_client):
    assert [c["name"] for c in _children(book_client, _SITE_PATH)] == ["Book"]
    (work,) = _children(book_client, f"{_SITE_PATH}/Book")
    assert work["name"] == "Virtues and vices"
    assert work["kind"] == "directory"
    assert work["has_children"] is True
    assert work["aspects"] == ["wikitext", "props"]


def test_node_children_are_aspects_then_subpages_in_natural_order(book_client):
    children = _children(book_client, _book_node(BOOK))
    assert [c["name"] for c in children] == [
        "@wikitext",
        "@props",
        "Chapter 1",
        "Chapter 2",
        "Chapter 10",
        "Part 2",
    ]
    by_name = {c["name"]: c for c in children}
    assert by_name["@wikitext"]["kind"] == "file"
    assert by_name["Part 2"]["kind"] == "directory"


def test_synthetic_node_has_children_but_no_aspects(book_client):
    stat = book_client.get("/vfs/stat", params={"path": _book_node(f"{BOOK}/Part 2")})
    body = stat.json()
    assert body["exists"] is True
    assert body["kind"] == "directory"
    assert body["has_children"] is True
    assert body["aspects"] == []
    assert body["stable_id"] is None
    assert [
        c["name"] for c in _children(book_client, _book_node(f"{BOOK}/Part 2"))
    ] == ["Section 3"]


def test_leaf_title_is_a_node_without_children(book_client):
    body = book_client.get(
        "/vfs/stat", params={"path": _book_node(f"{BOOK}/Chapter 1")}
    ).json()
    assert body["kind"] == "directory"
    assert body["has_children"] is False
    assert body["aspects"] == ["wikitext", "props"]


def test_read_and_write_go_through_the_wikitext_aspect(book_client):
    path = _book_wikitext(f"{BOOK}/Chapter 1")
    r = book_client.get("/vfs/content", params={"path": path})
    assert base64.b64decode(r.json()["content_base64"]) == b"one"

    w = book_client.post(
        "/vfs/content",
        json={"path": path, "content_base64": _b64("edited"), "base_revid": 7},
    )
    assert w.json()["status"] == "ok"
    node = book_client.get(
        "/vfs/stat", params={"path": _book_node(f"{BOOK}/Chapter 1")}
    )
    assert node.json()["dirty"] is True


def test_bare_node_path_is_not_a_file(book_client):
    r = book_client.get("/vfs/content", params={"path": _book_node(BOOK)})
    assert r.status_code == 400
    w = book_client.post(
        "/vfs/content",
        json={"path": _book_node(BOOK), "content_base64": _b64("x"), "base_revid": 7},
    )
    assert w.json()["status"] == "error"


def test_props_aspect_is_a_read_only_json_view(book_client):
    path = f"{_book_node(BOOK)}/@props"
    stat = book_client.get("/vfs/stat", params={"path": path}).json()
    assert stat["kind"] == "file"
    assert stat["content_model"] == "json"

    r = book_client.get("/vfs/content", params={"path": path})
    props = json.loads(base64.b64decode(r.json()["content_base64"]))
    assert props["title"] == BOOK
    assert props["namespace"] == "Book"
    assert props["revid"] == 7
    assert props["dirty"] is False
    assert stat["length"] == len(base64.b64decode(r.json()["content_base64"]))

    w = book_client.post(
        "/vfs/content",
        json={"path": path, "content_base64": _b64("{}"), "base_revid": 7},
    )
    assert w.json()["status"] == "error"
    assert "read-only" in w.json()["message"]


def test_stat_bulk_agrees_for_generic_titles(book_client):
    paths = [
        _book_wikitext(BOOK),
        _book_wikitext(f"{BOOK}/Chapter 2"),
        _book_wikitext(f"{BOOK}/Part 2"),
        _book_node(f"{BOOK}/Part 2"),
        f"{_book_node(BOOK)}/@props",
        _book_wikitext(f"{BOOK}/NoSuch"),
    ]
    results = book_client.post("/vfs/stat/bulk", json={"paths": paths}).json()[
        "results"
    ]
    for path, result in zip(paths, results):
        assert result == book_client.get("/vfs/stat", params={"path": path}).json()
