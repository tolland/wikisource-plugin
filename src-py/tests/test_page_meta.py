import pytest
from sqlmodel import Session

from wtbot.model import Page, Site
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import default_short_name
from wtbot.vfs.store import PageStore

"""Tests for the per-role Page metadata extensions (IndexMeta / PageMeta /
FileMeta): short_name derivation, store fetch-or-create, and the HTTP
upsert endpoints with their role guards and per-site uniqueness."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
PAGE_1 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1"
FILE = "File:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"


def _seed_site(session: Session, family: str = FAMILY, code: str = CODE) -> Site:
    site = Site(family=family, code=code)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def _add_page(
    session: Session,
    site: Site,
    title: str,
    role: NsRole,
    cm: str,
    index_title: str | None = None,
) -> Page:
    page = Page(
        site_pk=site.pk,
        title=title,
        namespace_role=role,
        content_model=cm,
        index_title=index_title,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def _seed_index(session: Session, site: Site, title: str = INDEX) -> Page:
    return _add_page(session, site, title, NsRole.index, "proofread-index")


# -- default_short_name --------------------------------------------------------


def test_default_short_name_tractatus():
    assert (
        default_short_name(INDEX) == "Wittgenstein-Tractatus_Logico-Philosophicus_1922"
    )


def test_default_short_name_simple():
    assert default_short_name("Index:Foo.djvu") == "Foo"


def test_default_short_name_strips_unsafe_chars():
    assert default_short_name('Index:A "B" (C) & D.pdf') == "A_B_C_D"


# -- PageStore.ensure_index_meta ------------------------------------------------


def test_ensure_index_meta_creates_default_and_is_idempotent(session):
    site = _seed_site(session)
    index = _seed_index(session, site)
    store = PageStore(session)

    meta = store.ensure_index_meta(index)
    assert meta.short_name == "Wittgenstein-Tractatus_Logico-Philosophicus_1922"
    assert store.ensure_index_meta(index).pk == meta.pk


def test_ensure_index_meta_deconflicts_same_site_defaults(session):
    site = _seed_site(session)
    a = _seed_index(session, site, "Index:Foo.djvu")
    b = _seed_index(session, site, "Index:Foo.pdf")  # same default 'Foo'
    store = PageStore(session)

    assert store.ensure_index_meta(a).short_name == "Foo"
    assert store.ensure_index_meta(b).short_name == "Foo_2"


def test_ensure_index_meta_same_default_ok_across_sites(session):
    site_a = _seed_site(session, code="en")
    site_b = _seed_site(session, code="de")
    a = _seed_index(session, site_a, "Index:Foo.djvu")
    b = _seed_index(session, site_b, "Index:Foo.djvu")
    store = PageStore(session)

    assert store.ensure_index_meta(a).short_name == "Foo"
    assert store.ensure_index_meta(b).short_name == "Foo"


# -- HTTP endpoints --------------------------------------------------------------


@pytest.fixture
def seeded(engine):
    # Close the seeding session before requests run — fixtures must not
    # hold a transaction open while the client's own sessions do work.
    with Session(engine) as s:
        site = _seed_site(s)
        index = _seed_index(s, site)
        page = _add_page(
            s, site, PAGE_1, NsRole.page, "proofread-page", index_title=INDEX
        )
        file_page = _add_page(s, site, FILE, NsRole.file, "wikitext")
        other_index = _seed_index(s, site, "Index:Other.djvu")
        pks = {
            "index_pk": index.pk,
            "page_pk": page.pk,
            "file_pk": file_page.pk,
            "other_index_pk": other_index.pk,
        }
    return pks


def test_index_meta_ensure_then_get(client, seeded):
    assert client.get(f"/pages/{seeded['index_pk']}/index-meta").status_code == 404

    r = client.post(f"/pages/{seeded['index_pk']}/index-meta/ensure")
    assert r.status_code == 200
    assert r.json()["short_name"] == "Wittgenstein-Tractatus_Logico-Philosophicus_1922"

    r = client.get(f"/pages/{seeded['index_pk']}/index-meta")
    assert r.status_code == 200


def test_index_meta_put_renames(client, seeded):
    r = client.put(
        f"/pages/{seeded['index_pk']}/index-meta", json={"short_name": "Tractatus"}
    )
    assert r.status_code == 200
    assert r.json()["short_name"] == "Tractatus"

    # Renaming to the same value again is not a conflict.
    r = client.put(
        f"/pages/{seeded['index_pk']}/index-meta", json={"short_name": "Tractatus"}
    )
    assert r.status_code == 200


def test_index_meta_put_rejects_unsafe_name(client, seeded):
    r = client.put(
        f"/pages/{seeded['index_pk']}/index-meta", json={"short_name": "no spaces!"}
    )
    assert r.status_code == 400


def test_index_meta_put_conflict_within_site(client, seeded):
    r = client.put(
        f"/pages/{seeded['index_pk']}/index-meta", json={"short_name": "Tractatus"}
    )
    assert r.status_code == 200
    r = client.put(
        f"/pages/{seeded['other_index_pk']}/index-meta",
        json={"short_name": "Tractatus"},
    )
    assert r.status_code == 409


def test_index_meta_rejected_for_non_index(client, seeded):
    r = client.put(f"/pages/{seeded['page_pk']}/index-meta", json={"short_name": "X"})
    assert r.status_code == 400


def test_page_meta_upsert_is_partial(client, seeded):
    pk = seeded["page_pk"]
    r = client.put(
        f"/pages/{pk}/page-meta",
        json={"thumb_url": "https://ws.example/thumb/159.jpg", "thumb_width": 400},
    )
    assert r.status_code == 200

    # Second PUT with a different field must not clobber the first.
    r = client.put(f"/pages/{pk}/page-meta", json={"raster_path": "/blobs/ab/cd"})
    assert r.status_code == 200
    body = client.get(f"/pages/{pk}/page-meta").json()
    assert body["thumb_url"] == "https://ws.example/thumb/159.jpg"
    assert body["thumb_width"] == 400
    assert body["raster_path"] == "/blobs/ab/cd"


def test_page_meta_rejected_for_non_page(client, seeded):
    r = client.put(f"/pages/{seeded['file_pk']}/page-meta", json={"thumb_width": 1})
    assert r.status_code == 400


def test_file_meta_records_provenance(client, seeded):
    pk = seeded["file_pk"]
    r = client.put(
        f"/pages/{pk}/file-meta",
        json={
            "origin": "paste",
            "source_page_pk": seeded["page_pk"],
            "source_page_number": 159,
            "crop_x": 120,
            "crop_y": 340,
            "crop_w": 800,
            "crop_h": 600,
        },
    )
    assert r.status_code == 200
    body = client.get(f"/pages/{pk}/file-meta").json()
    assert body["origin"] == "paste"
    assert body["source_page_number"] == 159
    assert body["crop_w"] == 800


def test_file_meta_rejected_for_non_file(client, seeded):
    r = client.put(f"/pages/{seeded['index_pk']}/file-meta", json={"origin": "paste"})
    assert r.status_code == 400


def test_meta_404_for_missing_page(client, seeded):
    assert client.get("/pages/99999/index-meta").status_code == 404
    assert client.put("/pages/99999/page-meta", json={}).status_code == 404


# -- /pages/resolve — identity bridge -------------------------------------------

_INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"


def test_resolve_by_vfs_path(client, seeded):
    r = client.get("/pages/resolve", params={"path": f"{_INDEX_PATH}/Pages/{PAGE_1}"})
    assert r.status_code == 200
    body = r.json()
    assert body["pk"] == seeded["page_pk"]
    assert body["title"] == PAGE_1

    # Index dir resolves to the Index page itself (dual role).
    r = client.get("/pages/resolve", params={"path": _INDEX_PATH})
    assert r.json()["pk"] == seeded["index_pk"]
    # ...as does its synthetic wikitext leaf.
    r = client.get("/pages/resolve", params={"path": f"{_INDEX_PATH}/wikitext"})
    assert r.json()["pk"] == seeded["index_pk"]


def test_resolve_by_title_triple(client, seeded):
    r = client.get(
        "/pages/resolve",
        params={"family": FAMILY, "code": CODE, "title": PAGE_1},
    )
    assert r.status_code == 200
    assert r.json()["pk"] == seeded["page_pk"]


def test_resolve_missing_and_bad_requests(client, seeded):
    r = client.get("/pages/resolve", params={"path": f"{_INDEX_PATH}/Pages/Page:No/9"})
    assert r.status_code == 404
    # Synthetic containers have no backing page.
    r = client.get("/pages/resolve", params={"path": f"{_INDEX_PATH}/Pages"})
    assert r.status_code == 404
    r = client.get(
        "/pages/resolve",
        params={"family": FAMILY, "code": CODE, "title": "Page:No/9"},
    )
    assert r.status_code == 404
    assert client.get("/pages/resolve").status_code == 400


def test_resolve_then_meta_roundtrip(client, seeded):
    """The intended flow: VFS path -> pk -> per-role metadata."""
    pk = client.get(
        "/pages/resolve", params={"path": f"{_INDEX_PATH}/Pages/{PAGE_1}"}
    ).json()["pk"]
    r = client.put(f"/pages/{pk}/page-meta", json={"thumb_width": 240})
    assert r.status_code == 200
