"""Registering a wiki, and addressing it by the name you gave it.

The behaviour under test is a refusal: a fetch naming an unregistered site is
an error. It used to create one -- a wiki nobody had configured, with no
credentials -- and then read from it. The first sign was a log line, long after
the fact, and the fix was invisible because nothing told you which site it
meant.
"""

import pytest
from conftest import register_site
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import FetchRequest, Site
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage


@pytest.fixture
def http(engine):
    wiki = FakeWikiClient(
        pages={
            "Page:Book.djvu/1": RemotePage(
                title="Page:Book.djvu/1",
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="body",
                revid=1,
            )
        }
    )
    app = create_app(engine=engine, client_factory=lambda site: wiki)
    with TestClient(app) as c:
        yield c


def test_a_site_is_addressed_by_its_label(http):
    register_site(http, label="local", family="mywikisource", code="en")

    resolved = http.get("/sites/by-label/local")
    assert resolved.status_code == 200
    assert resolved.json()["family"] == "mywikisource"


def test_fetching_an_unregistered_site_is_refused_and_says_what_exists(http, engine):
    """The refusal that is the point of all this. It must also be *useful*:
    a typo is the likely cause, so the error lists what is registered."""
    register_site(http, label="local", family="mywikisource", code="en")

    resp = http.post("/fetch/", json={"title": "Page:Book.djvu/1", "label": "lcoal"})

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "lcoal" in detail
    assert "local" in detail, "the error should list the labels that do exist"
    assert "wtbot site add" in detail

    # ...and nothing was registered or queued as a side effect of asking.
    with Session(engine) as session:
        assert len(session.exec(select(Site)).all()) == 1
        assert session.exec(select(FetchRequest)).all() == []


def test_fetching_with_no_sites_at_all_says_so(http):
    resp = http.post("/fetch/", json={"title": "Page:Book.djvu/1", "label": "local"})
    assert resp.status_code == 404
    assert "None registered" in resp.json()["detail"]


def test_refresh_also_refuses_an_unknown_label(http):
    resp = http.post("/fetch/refresh", json={"label": "nope"})
    assert resp.status_code == 404


def test_a_label_cannot_be_reused(http):
    register_site(http, label="local", family="mywikisource", code="en")

    clash = http.post(
        "/sites/", json={"label": "local", "family": "other", "code": "fr"}
    )

    assert clash.status_code == 409
    assert "local" in clash.json()["detail"]


def test_one_wiki_cannot_be_registered_twice_under_two_labels(http):
    """(family, code) stays unique too: two labels for one wiki would give a
    page two cache identities, and pageids only mean anything per wiki."""
    register_site(http, label="local", family="mywikisource", code="en")

    clash = http.post(
        "/sites/", json={"label": "local-again", "family": "mywikisource", "code": "en"}
    )

    assert clash.status_code == 409
    assert "local" in clash.json()["detail"], "should name the existing label"


def test_registering_requires_a_label(http):
    resp = http.post("/sites/", json={"family": "mywikisource", "code": "en"})
    assert resp.status_code == 422


def test_fetching_a_site_that_cannot_log_in_is_refused(http):
    """wtbot authenticates by default.

    Not because the published rate-limit table demands it -- it does not -- but
    because this backs an editor (commits need an account) and because
    Wikimedia's CDN refuses unauthenticated traffic unevenly and without
    documenting it, so reads that work now can stop working in ten minutes.
    Refused at queue time, since the drain that would fail is minutes and
    hundreds of pages later.
    """
    register_site(http, label="anon", family="mywikisource", code="en", username=None)

    resp = http.post("/fetch/", json={"title": "Page:Book.djvu/1", "label": "anon"})

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "no credential" in detail
    assert "site-credential add" in detail
    assert "WTBOT_ALLOW_ANONYMOUS" in detail


def test_the_anonymous_escape_hatch_works_and_is_not_silent(
    http, engine, monkeypatch, caplog
):
    """For the case it exists for -- reading a public wiki from a
    workstation -- and loud about it, because a rule that can be switched off
    quietly is not a rule."""
    import logging

    register_site(http, label="anon", family="mywikisource", code="en", username=None)
    monkeypatch.setenv("WTBOT_ALLOW_ANONYMOUS", "1")

    with caplog.at_level(logging.WARNING):
        resp = http.post("/fetch/", json={"title": "Page:Book.djvu/1", "label": "anon"})

    assert resp.status_code == 202
    assert any("WTBOT_ALLOW_ANONYMOUS" in r.message for r in caplog.records)


def test_a_registered_site_can_be_fetched_from(http, engine):
    site = register_site(http, label="local", family="mywikisource", code="en")

    resp = http.post("/fetch/", json={"title": "Page:Book.djvu/1", "label": "local"})

    assert resp.status_code == 202
    with Session(engine) as session:
        queued = session.exec(select(FetchRequest)).one()
        assert queued.site_pk == site["pk"]
