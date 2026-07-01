"""Tests for SiteCredential CRUD and the DB-aware client factory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.sqlmodel import Site, SiteCredential
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.types import RemotePage


@pytest.fixture
def app_client(engine):
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        yield c, engine


def _create_site(client: TestClient) -> dict:
    r = client.post("/sites/", json={"family": "mywikisource", "code": "en"})
    assert r.status_code == 201
    return r.json()


def test_put_credential_creates_and_returns(app_client):
    client, _ = app_client
    site = _create_site(client)
    r = client.put(
        f"/sites/{site['pk']}/credential",
        json={"username": "Admin", "password": "secret", "bot_name": "wtbot"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "Admin"
    assert body["password"] == "secret"
    assert body["bot_name"] == "wtbot"
    assert body["site_pk"] == site["pk"]


def test_put_credential_upserts(app_client):
    client, engine = app_client
    site = _create_site(client)
    client.put(f"/sites/{site['pk']}/credential", json={"username": "Alice", "password": "pw1"})
    r = client.put(f"/sites/{site['pk']}/credential", json={"username": "Alice", "password": "pw2"})
    assert r.status_code == 200
    assert r.json()["password"] == "pw2"

    with Session(engine) as s:
        rows = s.exec(select(SiteCredential)).all()
        assert len(rows) == 1  # still one row, not two


def test_get_credential(app_client):
    client, _ = app_client
    site = _create_site(client)
    client.put(f"/sites/{site['pk']}/credential", json={"username": "Bob", "password": "xyz"})
    r = client.get(f"/sites/{site['pk']}/credential")
    assert r.status_code == 200
    assert r.json()["username"] == "Bob"


def test_get_credential_missing_returns_404(app_client):
    client, _ = app_client
    site = _create_site(client)
    assert client.get(f"/sites/{site['pk']}/credential").status_code == 404


def test_delete_credential(app_client):
    client, _ = app_client
    site = _create_site(client)
    client.put(f"/sites/{site['pk']}/credential", json={"username": "Bob", "password": "xyz"})
    r = client.delete(f"/sites/{site['pk']}/credential")
    assert r.status_code == 204
    assert client.get(f"/sites/{site['pk']}/credential").status_code == 404


def test_put_credential_unknown_site_returns_404(app_client):
    client, _ = app_client
    r = client.put("/sites/9999/credential", json={"username": "x", "password": "y"})
    assert r.status_code == 404


def test_db_client_factory_uses_site_credential(engine):
    """The default factory picks up SiteCredential from DB and passes creds to WikiSettings."""
    from wtbot.main import _make_db_client_factory
    from wtbot.settings import WikiSettings

    captured: list[WikiSettings] = []

    def fake_get_wiki_client(settings: WikiSettings):
        captured.append(settings)
        return FakeWikiClient()

    site_pk: int
    with Session(engine) as s:
        site = Site(family="wikisource", code="en")
        s.add(site)
        s.commit()
        s.refresh(site)
        site_pk = site.pk
        cred = SiteCredential(site_pk=site_pk, username="Admin", password="secret", bot_name="wtbot")
        s.add(cred)
        s.commit()

    with Session(engine) as s:
        site_copy = s.get(Site, site_pk)

    import unittest.mock as mock

    factory = _make_db_client_factory(engine)
    with mock.patch("wtbot.main.get_wiki_client", side_effect=fake_get_wiki_client):
        factory(site_copy)

    assert len(captured) == 1
    s = captured[0]
    assert s.username == "Admin"
    assert s.password == "secret"
    assert s.bot_name == "wtbot"


def test_db_client_factory_anonymous_when_no_credential(engine):
    """Sites with no SiteCredential row get an anonymous WikiSettings."""
    from wtbot.main import _make_db_client_factory
    from wtbot.settings import WikiSettings

    captured: list[WikiSettings] = []

    def fake_get_wiki_client(settings: WikiSettings):
        captured.append(settings)
        return FakeWikiClient()

    site_pk: int
    with Session(engine) as s:
        site = Site(family="wikisource", code="en")
        s.add(site)
        s.commit()
        site_pk = site.pk

    with Session(engine) as s:
        site_copy = s.get(Site, site_pk)

    import unittest.mock as mock

    factory = _make_db_client_factory(engine)
    with mock.patch("wtbot.main.get_wiki_client", side_effect=fake_get_wiki_client):
        factory(site_copy)

    assert captured[0].username is None
    assert captured[0].password is None
