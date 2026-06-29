"""End-to-end of the cache-fill path with a network-free fake wiki client:
enqueue via the API -> worker drains -> page written back to SQLite."""

import pytest
from fastapi.testclient import TestClient

from wtbot.main import create_app
from wtbot.sqlmodel import FetchStatus, Page
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.types import RemotePage


def _remote(title, content_model, ns_canonical, ns_key):
    return RemotePage(
        title=title,
        namespace_key=ns_key,
        namespace_canonical=ns_canonical,
        content_model=content_model,
        text="{{:MediaWiki:Proofreadpage_index_template|...}}",
        pageid=42,
        revid=23417,
        user="someeditor",
        comment="tweak",
        sha1="7ea25a6970ea3470958843030de6e38783beeeda",
        size=2601,
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

    from sqlmodel import Session, select

    with Session(engine) as s:
        rows = s.exec(select(Page).where(Page.title == index_remote.title)).all()
        assert len(rows) == 1
