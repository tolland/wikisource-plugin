import base64

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import Page, Site
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePageImages

"""Tests for the /preview endpoints (split-editor live preview + page scan)."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Austin-HowToDoThingsWithWords-1962.pdf"
PAGE = "Page:Austin-HowToDoThingsWithWords-1962.pdf/100"


def _decode(payload: dict) -> str:
    return base64.b64decode(payload["html_base64"]).decode()


class RecordingWikiClient(FakeWikiClient):
    """FakeWikiClient that records render_preview/get_page_images calls."""

    def __init__(self, page_images=None):
        super().__init__(page_images=page_images)
        self.render_calls: list[tuple[str, str, str | None]] = []
        self.image_lookups: list[str] = []

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
        s.add(
            Page(
                site_pk=site.pk,
                title=PAGE,
                namespace_role=NsRole.page,
                content_model="proofread-page",
                text="old cached body",
                index_title=INDEX,
            )
        )
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


PAGE_PATH = f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE}"
SCAN_URL = "https://uploads.example/scan/100.jpg"
FRESH_SCAN_URL = "https://uploads.example/scan/replacement-100.jpg"


@pytest.fixture
def fetched_images(monkeypatch) -> dict[str, tuple[bytes, str] | None]:
    """Route _fetch_image through an in-test URL→result table instead of the
    network. Unknown URLs behave like dead links (None)."""
    table: dict[str, tuple[bytes, str] | None] = {}
    monkeypatch.setattr("wtbot.api.preview._fetch_image", lambda url: table.get(url))
    return table


def _page_pk(engine) -> int:
    with Session(engine) as s:
        return s.exec(select(Page).where(Page.title == PAGE)).one().pk


def _add_page_meta(engine, url: str) -> None:
    with Session(engine) as s:
        s.add(PageMeta(page_pk=_page_pk(engine), source_image_url=url))
        s.commit()


def test_page_image_no_scan_anywhere_returns_placeholder(
    preview_client, fetched_images
):
    resp = preview_client.get("/preview/page-image", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert PAGE in resp.text


def test_page_image_proxies_cached_pagemeta_url(
    preview_client, engine, wiki_client, fetched_images
):
    _add_page_meta(engine, SCAN_URL)
    fetched_images[SCAN_URL] = (b"JPEGBYTES", "image/jpeg")

    resp = preview_client.get("/preview/page-image", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.content == b"JPEGBYTES"
    assert resp.headers["content-type"] == "image/jpeg"
    assert "max-age" in resp.headers["cache-control"]
    # cache hit — no live lookup needed
    assert wiki_client.image_lookups == []


def test_page_image_stale_cached_url_heals_from_live_lookup(
    preview_client, engine, wiki_client, fetched_images
):
    """The backing File: was replaced: the cached URL is dead, but a single
    imageforpage lookup finds the fresh one, which is persisted back."""
    _add_page_meta(engine, SCAN_URL)  # dead: not in fetched_images
    wiki_client._page_images[PAGE] = RemotePageImages(fullsize_url=FRESH_SCAN_URL)
    fetched_images[FRESH_SCAN_URL] = (b"FRESH", "image/png")

    resp = preview_client.get("/preview/page-image", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.content == b"FRESH"
    assert wiki_client.image_lookups == [PAGE]

    with Session(engine) as s:
        meta = s.exec(
            select(PageMeta).where(PageMeta.page_pk == _page_pk(engine))
        ).one()
        assert meta.source_image_url == FRESH_SCAN_URL


def test_page_image_deleted_file_degrades_to_placeholder(
    preview_client, engine, wiki_client, fetched_images
):
    """File: deleted outright: dead cached URL, live lookup finds nothing —
    placeholder, exactly one lookup, no retry loop."""
    _add_page_meta(engine, SCAN_URL)  # dead

    resp = preview_client.get("/preview/page-image", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert wiki_client.image_lookups == [PAGE]


def test_page_image_uncached_page_uses_live_lookup(
    preview_client, engine, wiki_client, fetched_images
):
    """No PageMeta yet (fetched before scan support): live lookup fills in."""
    wiki_client._page_images[PAGE] = RemotePageImages(fullsize_url=FRESH_SCAN_URL)
    fetched_images[FRESH_SCAN_URL] = (b"LATE", "image/jpeg")

    resp = preview_client.get("/preview/page-image", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.content == b"LATE"

    with Session(engine) as s:
        meta = s.exec(
            select(PageMeta).where(PageMeta.page_pk == _page_pk(engine))
        ).first()
        assert meta is not None and meta.source_image_url == FRESH_SCAN_URL


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
