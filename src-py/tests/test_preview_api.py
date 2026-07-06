import base64

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from wtbot.main import create_app
from wtbot.model import Page, Site
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta
from wtbot.wiki.client import FakeWikiClient

"""Tests for the /preview/render endpoint (plugin split-editor live preview)."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Austin-HowToDoThingsWithWords-1962.pdf"
PAGE = "Page:Austin-HowToDoThingsWithWords-1962.pdf/100"


def _decode(payload: dict) -> str:
    return base64.b64decode(payload["html_base64"]).decode()


class RecordingWikiClient(FakeWikiClient):
    """FakeWikiClient that records render_preview calls for assertions."""

    def __init__(self):
        super().__init__()
        self.render_calls: list[tuple[str, str, str | None]] = []

    def render_preview(self, title, wikitext, content_model=None):
        self.render_calls.append((title, wikitext, content_model))
        return super().render_preview(title, wikitext, content_model)

    def get_page_images(self, title):
        self.image_lookups.append(title)
        return super().get_page_images(title)


@pytest.fixture
def wiki_client() -> RecordingWikiClient:
    return RecordingWikiClient()


@pytest.fixture
def preview_client(engine, wiki_client) -> TestClient:
    app = create_app(engine=engine, client_factory=lambda site: wiki_client)
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        page = Page(
            site_pk=site.pk,
            title=PAGE,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text="old cached body",
        )
        s.add(page)
        s.flush()
        s.add(PageMeta(page_pk=page.pk, index_title=INDEX))
        s.commit()
    with TestClient(app) as c:
        yield c


def test_render_by_vfs_path_uses_cached_content_model(preview_client, wiki_client):
    resp = preview_client.post(
        "/preview/render",
        json={
            "path": f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE}",
            "wikitext": "Hello ''world''",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == PAGE
    assert "Hello" in _decode(data)
    assert wiki_client.render_calls == [(PAGE, "Hello ''world''", "proofread-page")]


def test_render_page_directly_under_index_path(preview_client, wiki_client):
    resp = preview_client.post(
        "/preview/render",
        json={"path": f"/{FAMILY}/{CODE}/{INDEX}/{PAGE}", "wikitext": "x"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == PAGE


def test_render_index_wikitext_path(preview_client, wiki_client):
    resp = preview_client.post(
        "/preview/render",
        json={"path": f"/{FAMILY}/{CODE}/{INDEX}/wikitext", "wikitext": "<pagelist />"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == INDEX
    # not in the Page cache → content model left for the wiki to infer
    assert wiki_client.render_calls[-1] == (INDEX, "<pagelist />", None)


def test_render_by_bare_title_uses_first_site(preview_client, wiki_client):
    resp = preview_client.post(
        "/preview/render",
        json={"title": "Sandbox", "wikitext": "{{test}}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Sandbox"
    assert "{{test}}" in _decode(data)


def test_render_html_is_escaped_json_safe(preview_client):
    resp = preview_client.post(
        "/preview/render",
        json={"title": "Sandbox", "wikitext": 'a "quoted" <tag>\nline'},
    )
    assert resp.status_code == 200
    html = _decode(resp.json())
    assert "&quot;quoted&quot;" in html
    assert "&lt;tag&gt;" in html


def test_render_unknown_site_404(preview_client):
    resp = preview_client.post(
        "/preview/render",
        json={"path": "/wikipedia/de/Index:X.pdf/Page:X.pdf/1", "wikitext": "x"},
    )
    assert resp.status_code == 404


def test_render_needs_path_or_title(preview_client):
    resp = preview_client.post("/preview/render", json={"wikitext": "x"})
    assert resp.status_code == 422


def test_render_no_sites_configured_404(engine):
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with TestClient(app) as c:
        resp = c.post("/preview/render", json={"title": "X", "wikitext": "x"})
        assert resp.status_code == 404


def test_page_image_by_path_labels_placeholder_with_title(preview_client):
    resp = preview_client.get(
        "/preview/page-image",
        params={"path": f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert PAGE in resp.text


def test_page_image_by_title(preview_client):
    resp = preview_client.get("/preview/page-image", params={"title": "Page:X.pdf/1"})
    assert resp.status_code == 200
    assert "Page:X.pdf/1" in resp.text


def test_page_image_escapes_title_for_svg(preview_client):
    resp = preview_client.get(
        "/preview/page-image", params={"title": 'Page:A&B <"quoted">.pdf/1'}
    )
    assert resp.status_code == 200
    assert "Page:A&amp;B &lt;" in resp.text


def test_page_image_needs_path_or_title(preview_client):
    resp = preview_client.get("/preview/page-image")
    assert resp.status_code == 422


def test_render_wiki_failure_becomes_502(engine):
    class ExplodingClient(FakeWikiClient):
        def render_preview(self, title, wikitext, content_model=None):
            raise RuntimeError("wiki is down")

    app = create_app(engine=engine, client_factory=lambda site: ExplodingClient())
    with Session(engine) as s:
        s.add(Site(family=FAMILY, code=CODE))
        s.commit()
    with TestClient(app) as c:
        resp = c.post("/preview/render", json={"title": "X", "wikitext": "x"})
        assert resp.status_code == 502
        assert "wiki is down" in resp.json()["detail"]
