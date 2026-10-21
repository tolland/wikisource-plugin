"""End-to-end of the sync-back path: local save via /vfs/content -> POST
/commit/ drains EditJournal -> page pushed to the wiki via FakeWikiClient."""

from __future__ import annotations

import base64

import pytest
from conftest import FAKE_TIMESTAMP, add_proofread_meta, fake_pageid, make_page
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import (
    Commit,
    CommitStatus,
    EditJournal,
    FetchRequest,
    FetchStatus,
    Page,
    Site,
)
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

TITLE = "Page:Foo.djvu/1"
INDEX_TITLE = "Index:Foo.djvu"
PATH = "/wikisource/en/Page:Foo.djvu/1"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _setup(engine):
    with Session(engine) as s:
        site = Site(family="wikisource", code="en")
        s.add(site)
        s.commit()
        s.refresh(site)

        # The VFS resolves Pages/ paths through their Index: page and the
        # page's index_title link, so the fixture must model the cache state
        # the fetch worker actually produces: index row + linked page.
        s.add(
            make_page(
                site_pk=site.pk,
                title=INDEX_TITLE,
                content_model="proofread-index",
            )
        )
        page = make_page(
            site_pk=site.pk,
            title=TITLE,
            content_model="proofread-page",
            text="original",
            revid=100,
        )
        s.add(page)
        s.flush()
        add_proofread_meta(s, page_pk=page.pk, index_title=INDEX_TITLE)
        s.commit()
        s.refresh(page)
        return site, page


@pytest.mark.parametrize("single", [False, True])
def test_commit_endpoint_pushes_pending_edits(engine, single, caplog):
    caplog.set_level("INFO", logger="wtbot.api.commit")
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
                pageid=fake_pageid(TITLE),
                timestamp=FAKE_TIMESTAMP,
            )
        }
    )
    with Session(engine) as session:
        unrelated = FetchRequest(site_pk=page.site_pk, title="Unrelated", priority=100)
        session.add(unrelated)
        session.commit()
        unrelated_pk = unrelated.pk
    app = create_app(engine=engine, client_factory=lambda site: fake)
    with TestClient(app) as c:
        write = c.post(
            "/vfs/content",
            json={"path": PATH, "content_base64": _b64("edited"), "base_revid": 100},
        )
        assert write.status_code == 200
        assert write.json()["status"] == "ok"

        resp = c.post(f"/commits/{page.pk}" if single else "/commits/")
        assert resp.status_code == 200
        assert (
            resp.json()["status"] == "success"
            if single
            else resp.json()["handled"] == 1
        )

        # TestClient waits for background tasks: no manual refresh/drain is needed.
        with Session(engine) as session:
            assert session.get(Page, page.pk).text == "edited"
            assert session.get(FetchRequest, unrelated_pk).status == FetchStatus.pending

        read = c.get("/vfs/content", params={"path": PATH}).json()
        assert base64.b64decode(read["content_base64"]).decode() == "edited"
        assert read["revid"] == 101

    assert "commit refetch started: 1 queued request(s)" in caplog.text
    assert (
        "commit refetch finished: handled=1 complete=1 errors=0 remaining=0"
        in caplog.text
    )

    assert fake._pages[TITLE].text == "edited"

    with Session(engine) as s:
        updated = s.get(Page, page.pk)
        assert updated.revid == 101
        assert updated.text == "edited"  # snapshot trued up by the refetch
        assert updated.address.dirty is False

        journal = s.exec(
            select(EditJournal).where(EditJournal.title_pk == page.pk)
        ).all()
        assert all(j.committed for j in journal)

        commit = s.exec(select(Commit).where(Commit.title_pk == page.pk)).first()
        assert commit.status == CommitStatus.success
        assert commit.result_revid == 101


def test_pending_commits_include_original_body_for_diff(engine):
    _setup(engine)
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        write = c.post(
            "/vfs/content",
            json={"path": PATH, "content_base64": _b64("edited"), "base_revid": 100},
        )
        assert write.status_code == 200

        resp = c.get("/commits/pending")
        assert resp.status_code == 200
        [pending] = resp.json()
        assert pending["base_body"] == "original"
        assert pending["submitted_body"] == "edited"


def test_commit_endpoint_can_force_overwrite_conflict(engine):
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="someone else's edit",
                revid=200,
                pageid=fake_pageid(TITLE),
                timestamp=FAKE_TIMESTAMP,
            )
        }
    )
    app = create_app(engine=engine, client_factory=lambda site: fake)
    with TestClient(app) as c:
        write = c.post(
            "/vfs/content",
            json={"path": PATH, "content_base64": _b64("edited"), "base_revid": 100},
        )
        assert write.status_code == 200

        resp = c.post(f"/commits/{page.pk}?force=true", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["base_revid"] == 100
        assert resp.json()["result_revid"] == 201

    assert fake._pages[TITLE].text == "edited"


def test_commit_endpoint_accepts_edit_summary_override(engine):
    _, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
                pageid=fake_pageid(TITLE),
                timestamp=FAKE_TIMESTAMP,
            )
        }
    )
    app = create_app(engine=engine, client_factory=lambda site: fake)
    with TestClient(app) as c:
        assert (
            c.post(
                "/vfs/content",
                json={
                    "path": PATH,
                    "content_base64": _b64("edited"),
                    "base_revid": 100,
                    "comment": "journal summary",
                },
            ).status_code
            == 200
        )

        resp = c.post(f"/commits/{page.pk}", json={"comment": "reviewed summary"})

    assert resp.status_code == 200
    assert resp.json()["comment"] == "reviewed summary"
    assert fake._pages[TITLE].comment == "reviewed summary"


def test_cancel_pending_commit_discards_local_edits(engine):
    site, page = _setup(engine)
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        write = c.post(
            "/vfs/content",
            json={"path": PATH, "content_base64": _b64("edited"), "base_revid": 100},
        )
        assert write.status_code == 200

        resp = c.delete(f"/commits/{page.pk}/pending")
        assert resp.status_code == 200
        assert resp.json()["handled"] == 1

        pending = c.get("/commits/pending")
        assert pending.status_code == 200
        assert pending.json() == []

    with Session(engine) as s:
        assert (
            s.exec(select(EditJournal).where(EditJournal.title_pk == page.pk)).all()
            == []
        )
        updated = s.get(Page, page.pk)
        assert updated.address.dirty is False
        assert updated.text == "original"


def test_commit_endpoint_noop_when_nothing_pending(engine):
    _setup(engine)
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        resp = c.post("/commits/")
    assert resp.status_code == 200
    assert resp.json()["handled"] == 0


def test_bulk_and_single_stat_agree_during_the_push_window(engine):
    """The batched path must report what the single path reports.

    In the window between a successful push and its refetch, a page can carry
    both an uncommitted save (which supplies the body) and a commit ahead of
    the snapshot (which supplies the revid). The bulk path used to restate the
    bridging rule inline, and loaded commits only for pages *without* local
    edits -- so precisely this page reported a stale revid in a listing and a
    current one when stat'ed alone. Both now go through the same rule.
    """
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
                pageid=fake_pageid(TITLE),
                timestamp=FAKE_TIMESTAMP,
            )
        }
    )
    app = create_app(engine=engine, client_factory=lambda site: fake)
    with TestClient(app) as c:
        c.post(
            "/vfs/content",
            json={"path": PATH, "content_base64": _b64("pushed"), "base_revid": 100},
        )
        assert c.post("/commits/").json()["handled"] == 1

        # A further local save, still in the window: refetch not drained.
        c.post("/vfs/content", json={"path": PATH, "content_base64": _b64("and more")})

        single = c.get("/vfs/stat", params={"path": PATH}).json()
        bulk = c.post("/vfs/stat/bulk", json={"paths": [PATH]}).json()["results"][0]

    assert single == bulk
    assert single["revid"] == 101  # the revision we pushed, not the snapshot's
    assert single["placeholder"] is False


def test_failed_automatic_refetch_preserves_successful_commit(engine, monkeypatch):
    _, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
                pageid=fake_pageid(TITLE),
                timestamp=FAKE_TIMESTAMP,
            )
        }
    )

    def fail_read(titles):
        raise RuntimeError("wiki read unavailable")

    monkeypatch.setattr(fake, "get_pages", fail_read)
    app = create_app(engine=engine, client_factory=lambda site: fake)
    with TestClient(app) as client:
        assert (
            client.post(
                "/vfs/content",
                json={
                    "path": PATH,
                    "content_base64": _b64("edited"),
                    "base_revid": 100,
                },
            ).status_code
            == 200
        )
        response = client.post(f"/commits/{page.pk}")
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        read = client.get("/vfs/content", params={"path": PATH}).json()
        assert base64.b64decode(read["content_base64"]).decode() == "edited"

    with Session(engine) as session:
        assert session.get(Page, page.pk).text == "original"
        fetch = session.exec(select(FetchRequest)).one()
        assert fetch.status == FetchStatus.error
        assert "wiki read unavailable" in fetch.error_message
        assert session.exec(select(EditJournal)).one().committed
