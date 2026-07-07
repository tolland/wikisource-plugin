"""End-to-end of the sync-back path: local save via /vfs/content -> POST
/commit/ drains EditJournal -> page pushed to the wiki via FakeWikiClient."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import Commit, CommitStatus, EditJournal, Page, Site
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

TITLE = "Page:Foo.djvu/1"
INDEX_TITLE = "Index:Foo.djvu"
PATH = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"


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
            Page(
                site_pk=site.pk,
                title=INDEX_TITLE,
                namespace_role=NsRole.index,
                content_model="proofread-index",
            )
        )
        page = Page(
            site_pk=site.pk,
            title=TITLE,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text="original",
            revid=100,
        )
        s.add(page)
        s.flush()
        s.add(PageMeta(page_pk=page.pk, index_title=INDEX_TITLE))
        s.commit()
        s.refresh(page)
        return site, page


def test_commit_endpoint_pushes_pending_edits(engine):
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
        assert write.json()["status"] == "ok"

        resp = c.post("/commits/")
        assert resp.status_code == 200
        assert resp.json()["handled"] == 1

    assert fake._pages[TITLE].text == "edited"

    with Session(engine) as s:
        updated = s.get(Page, page.pk)
        assert updated.revid == 101
        assert updated.dirty is False

        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).all()
        assert all(j.committed for j in journal)

        commit = s.exec(select(Commit).where(Commit.page_pk == page.pk)).first()
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


def test_commit_endpoint_noop_when_nothing_pending(engine):
    _setup(engine)
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        resp = c.post("/commits/")
    assert resp.status_code == 200
    assert resp.json()["handled"] == 0
