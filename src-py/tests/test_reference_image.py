"""The reference image: the scan the transcriber reads from.

Named for what it is. It used to be ``GET /preview/page-image``, next door to
an endpoint that renders wikitext to HTML -- so one route called "preview"
returned markup and another returned a picture of a book page. The picture is
not a preview of anything; it is the source being transcribed, and
ProofreadPage's own API calls it ``imageforpage``.
"""

import pytest
from conftest import add_proofread_meta, make_page
from fastapi.testclient import TestClient
from sqlmodel import Session

from wtbot.main import create_app
from wtbot.model import Site
from wtbot.wiki.client import FakeWikiClient

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Austin-HowToDoThingsWithWords-1962.pdf"
PAGE = "Page:Austin-HowToDoThingsWithWords-1962.pdf/100"


@pytest.fixture
def client(engine) -> TestClient:
    app = create_app(engine=engine, client_factory=lambda site: FakeWikiClient())
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE, label="local")
        s.add(site)
        s.commit()
        s.refresh(site)
        page = make_page(
            site_pk=site.pk,
            title=PAGE,
            content_model="proofread-page",
            text="old cached body",
        )
        s.add(page)
        s.flush()
        add_proofread_meta(s, page_pk=page.pk, index_title=INDEX)
        s.commit()
    with TestClient(app) as c:
        yield c


def test_a_page_with_no_scan_yet_gets_a_labelled_placeholder(client):
    """Never a 404: the pane is part of the editor layout, and a broken image
    there is worse than a blank sheet that says which page is waiting."""
    resp = client.get(
        "/reference-image",
        params={"path": f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE}"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert PAGE in resp.text


def test_it_can_be_addressed_by_title_as_well_as_path(client):
    """Scratch .wt files hold a title and no VFS path."""
    resp = client.get("/reference-image", params={"title": "Page:X.pdf/1"})

    assert resp.status_code == 200
    assert "Page:X.pdf/1" in resp.text


def test_a_title_is_escaped_into_the_placeholder_svg(client):
    """The label is user data going into markup."""
    resp = client.get("/reference-image", params={"title": 'Page:A&B <"quoted">.pdf/1'})

    assert resp.status_code == 200
    assert "Page:A&amp;B &lt;" in resp.text


def test_it_needs_a_path_or_a_title(client):
    assert client.get("/reference-image").status_code == 422


def test_the_old_preview_path_is_gone(client):
    """The rename is a rename, not an alias. Both sides of this contract live
    in one repository, so a compatibility path would only preserve the
    misnomer it was made to remove."""
    resp = client.get("/preview/page-image", params={"title": "Page:X.pdf/1"})

    assert resp.status_code == 404


def test_preview_still_renders_markup(client):
    """The endpoint that *is* a preview, so the two stay distinguishable: this
    one answers with HTML from action=parse."""
    resp = client.post(
        "/preview/render",
        json={"path": f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE}", "wikitext": "hi"},
    )

    assert resp.status_code == 200
    assert "html_base64" in resp.json()


def _seed_scan(engine, url: str) -> None:
    from sqlmodel import select

    from wtbot.model import Title
    from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta

    with Session(engine) as s:
        page = s.exec(select(Title).where(Title.title == PAGE)).one()
        meta = s.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.title_pk == page.pk)
        ).one()
        meta.source_image_url = url
        s.add(meta)
        s.commit()


def test_an_updated_scan_replaces_the_cached_bytes(
    client, engine, tmp_path, monkeypatch
):
    """The wiki's thumb URL is stable across a re-upload, so the cache must
    revalidate rather than trust its own existence."""
    from wtbot.api import reference_image as ri

    served = {"body": b"v1", "etag": '"1"'}
    calls: list[str | None] = []

    def fake(url, validators):
        calls.append(validators.etag)
        if validators.etag == served["etag"]:
            return ri.FetchedImage(None, validators)
        return ri.FetchedImage(served["body"], ri.Validators(etag=served["etag"]))

    monkeypatch.setattr(ri, "fetch_image_if_changed", fake)
    client.app.state.blob_root = tmp_path
    _seed_scan(engine, "https://wiki.test/thumb/page1-800px-Book.pdf.jpg")
    params = {"title": PAGE}
    c = client
    assert c.get("/reference-image", params=params).content == b"v1"
    assert c.get("/reference-image", params=params).content == b"v1"  # 304

    served.update(body=b"v2", etag='"2"')
    assert c.get("/reference-image", params=params).content == b"v2"

    assert calls == [None, '"1"', '"1"']


def test_a_failed_revalidation_serves_the_cached_scan(
    client, engine, tmp_path, monkeypatch
):
    from wtbot.api import reference_image as ri

    state = {"up": True}

    def fake(url, validators):
        if not state["up"]:
            raise OSError("wiki down")
        return ri.FetchedImage(b"v1", ri.Validators())

    monkeypatch.setattr(ri, "fetch_image_if_changed", fake)
    client.app.state.blob_root = tmp_path
    _seed_scan(engine, "https://wiki.test/thumb/page1-800px-Book.pdf.jpg")
    c = client
    assert c.get("/reference-image", params={"title": PAGE}).content == b"v1"
    state["up"] = False
    resp = c.get("/reference-image", params={"title": PAGE})

    assert resp.status_code == 200
    assert resp.content == b"v1"
