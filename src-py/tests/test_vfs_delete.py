from __future__ import annotations

import pytest
from conftest import add_proofread_meta, make_page
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from wtbot.model import (
    Content,
    EditJournal,
    FetchRequest,
    Page,
    Revision,
    Site,
    Slot,
    Title,
)
from wtbot.model.fetch.fetch_request import FetchStatus

"""VFS delete: one node or a subtree, from the local cache only.

The motivating case is the shadow node -- a Title recorded for a non-canonical
spelling, which the wiki can never answer for -- so the tree below includes
two spellings of one title alongside a normal Index with Pages and an asset.
"""

FAMILY = "mywikisource"
CODE = "en"
SITE = f"/{FAMILY}/{CODE}"
INDEX = "Index:Book.djvu"
STYLES = f"{INDEX}/styles.css"
PAGE_1 = "Page:Book.djvu/1"
PAGE_2 = "Page:Book.djvu/2"
CANONICAL = "Book/The Philosophy of 'As If'"
SHADOW = "Book/The Philosophy of %27As If%27"


def _titles(engine) -> set[str]:
    with Session(engine) as s:
        return {t.title for t in s.exec(select(Title)).all()}


@pytest.fixture
def client(engine, tmp_path) -> TestClient:
    from wtbot.main import create_app

    app = create_app(engine=engine, blob_root=tmp_path / "blobs")
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.add_all(
            [
                make_page(
                    site_pk=site.pk, title=INDEX, content_model="proofread-index"
                ),
                make_page(site_pk=site.pk, title=STYLES, content_model="sanitized-css"),
                make_page(site_pk=site.pk, title=CANONICAL),
                make_page(site_pk=site.pk, title=f"{CANONICAL}/Notes"),
            ]
        )
        p1 = make_page(site_pk=site.pk, title=PAGE_1, content_model="proofread-page")
        p2 = make_page(site_pk=site.pk, title=PAGE_2, content_model="proofread-page")
        s.add_all([p1, p2])
        s.commit()
        add_proofread_meta(s, page_pk=p1.pk, index_title=INDEX, page_number=1)
        add_proofread_meta(s, page_pk=p2.pk, index_title=INDEX, page_number=2)
        # A title nothing can fetch: recorded, never held by the wiki.
        s.add(Title(site_pk=site.pk, title=SHADOW, expected_content_model="wikitext"))
        s.commit()
    with TestClient(app) as c:
        yield c


def _delete(client: TestClient, path: str, **params):
    return client.delete("/vfs/node", params={"path": path, **params})


def test_delete_shadow_node(client, engine):
    resp = _delete(client, f"{SITE}/{SHADOW}")
    assert resp.status_code == 200
    assert resp.json()["deleted_paths"] == [f"{SITE}/{SHADOW}"]
    titles = _titles(engine)
    assert SHADOW not in titles
    assert CANONICAL in titles
    assert (
        client.get("/vfs/stat", params={"path": f"{SITE}/{SHADOW}"}).json()["exists"]
        is False
    )


def test_delete_node_leaves_subpages(client, engine):
    resp = _delete(client, f"{SITE}/{CANONICAL}")
    assert resp.status_code == 200
    assert resp.json()["deleted_paths"] == [f"{SITE}/{CANONICAL}"]
    assert f"{CANONICAL}/Notes" in _titles(engine)


def test_delete_recursive_takes_subpages(client, engine):
    resp = _delete(client, f"{SITE}/{CANONICAL}", recursive=True)
    assert resp.json()["deleted_paths"] == sorted(
        [f"{SITE}/{CANONICAL}", f"{SITE}/{CANONICAL}/Notes"]
    )
    assert not {CANONICAL, f"{CANONICAL}/Notes"} & _titles(engine)
    assert SHADOW in _titles(engine)  # a different spelling is a different title


def test_delete_index_alone_is_refused_while_pages_depend_on_it(client, engine):
    resp = _delete(client, f"{SITE}/{INDEX}")
    assert resp.status_code == 409
    assert resp.json()["code"] == "delete-blocked"
    assert "recursive" in resp.json()["detail"]
    assert INDEX in _titles(engine)


def test_delete_index_recursive_takes_pages_and_assets(client, engine):
    resp = _delete(client, f"{SITE}/{INDEX}", recursive=True)
    assert resp.status_code == 200
    assert {INDEX, STYLES, PAGE_1, PAGE_2}.isdisjoint(_titles(engine))
    assert CANONICAL in _titles(engine)


def test_delete_page_alone_leaves_index(client, engine):
    assert _delete(client, f"{SITE}/{PAGE_1}").status_code == 200
    assert {INDEX, PAGE_2} <= _titles(engine)
    assert PAGE_1 not in _titles(engine)


def test_delete_refuses_uncommitted_edits_unless_discarded(client, engine):
    with Session(engine) as s:
        title = s.exec(select(Title).where(Title.title == PAGE_1)).one()
        s.add(EditJournal(title_pk=title.pk, base_revid=None, body="edited"))
        title.dirty = True
        s.add(title)
        s.commit()

    resp = _delete(client, f"{SITE}/{PAGE_1}")
    assert resp.status_code == 409
    assert PAGE_1 in resp.json()["detail"]
    assert PAGE_1 in _titles(engine)

    assert (
        _delete(client, f"{SITE}/{PAGE_1}", discard_local_edits=True).status_code == 200
    )
    with Session(engine) as s:
        assert s.exec(select(EditJournal)).all() == []


def test_delete_cascades_revisions_and_orphaned_content_only(client, engine):
    with Session(engine) as s:
        page = s.exec(
            select(Page).where(Page.pk == Title.pk, Title.title == PAGE_1)
        ).one()
        other = s.exec(
            select(Page).where(Page.pk == Title.pk, Title.title == PAGE_2)
        ).one()
        own = Content(content_sha1="own", text="a", size=1)
        shared = Content(content_sha1="shared", text="b", size=1)
        s.add_all([own, shared])
        s.commit()
        rev = Revision(page_pk=page.pk, revid=1)
        rev_b = Revision(page_pk=page.pk, revid=3)
        other_rev = Revision(page_pk=other.pk, revid=2)
        s.add_all([rev, rev_b, other_rev])
        s.commit()
        s.add_all(
            [
                Slot(revision_pk=rev.pk, content_pk=own.pk),
                Slot(revision_pk=rev_b.pk, content_pk=shared.pk),
                Slot(revision_pk=other_rev.pk, content_pk=shared.pk),
            ]
        )
        site_pk = page.site_pk
        s.add(FetchRequest(site_pk=site_pk, title=PAGE_1))
        s.commit()

    assert _delete(client, f"{SITE}/{PAGE_1}").status_code == 200
    with Session(engine) as s:
        assert {c.content_sha1 for c in s.exec(select(Content)).all()} == {"shared"}
        assert [r.revid for r in s.exec(select(Revision)).all()] == [2]
        (request,) = s.exec(select(FetchRequest)).all()
        assert request.status == FetchStatus.cancelled


@pytest.mark.parametrize(
    "path", ["", "/", SITE, f"{SITE}/{INDEX}/Pages", f"{SITE}/{INDEX}/wikitext"]
)
def test_delete_synthetic_nodes_refused(client, path):
    resp = _delete(client, path)
    assert resp.status_code == 400
    assert resp.json()["code"] == "not-deletable"


@pytest.mark.parametrize("path", [f"{SITE}/Nope", "/nowhere/xx/Nope"])
def test_delete_unknown_is_404(client, path):
    assert _delete(client, path).status_code == 404


def test_every_title_reference_is_either_cascaded_or_blocks():
    """Adding a table that points at a title must be a decision, not an
    accident: it either goes with the title (`delete_titles`) or stops a delete
    that would strand it (`blockers`). Update those and this list together."""
    handled = {
        # cascaded by delete_titles
        "page", "revision", "fileblob", "proofreadpagemeta", "indexmeta",
        "scanannotation", "boxrangelink", "texttargetanchor", "editjournal",
        "commit",
        # blocking in `blockers`
        "pagelink", "promotionbatch",
    }  # fmt: skip
    referencing = {
        table.name
        for table in SQLModel.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name in {"title", "page"}
    }
    assert referencing <= handled, referencing - handled
