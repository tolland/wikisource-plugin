"""VCR-backed integration tests for PywikibotClient.

These tests exercise the real pywikibot code path against recorded HTTP cassettes,
so responses are from actual MediaWiki API calls rather than hand-crafted fakes.

Two cassette sets:
  en_ws/  — en.wikisource.org (public, recordable from anywhere with internet)
  lan/    — wikisource-debian-13.lan (private; needs CA cert + LAN access to record)

Tests skip silently when a cassette doesn't exist yet.  Record with:
    VCR_RECORD_MODE=all uv run pytest src-py/tests/test_vcr_fetch.py -v

See src-py/tests/cassettes/README.md for full instructions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vcr_config import FIXTURES_DIR, cassette_exists, make_vcr
from wtbot.settings import WikiSettings
from wtbot.sqlmodel import FetchRequest, FetchStatus, FileBlob, Page
from wtbot.wiki.client import PywikibotClient

TRACTATUS_INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
TRACTATUS_FILE = "File:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
TRACTATUS_PAGE_1 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1"

# Real fixture blob — the user points TRACTATUS_DJVU_PATH at their local copy.
# If absent the download assertions are skipped; metadata assertions still run.
_TRACTATUS_DJVU = Path(
    os.environ.get(
        "TRACTATUS_DJVU_PATH",
        FIXTURES_DIR / "Wittgenstein_-_Tractatus_Logico-Philosophicus,_1922.djvu",
    )
)

_EN_VCR = make_vcr("en_ws")
_LAN_VCR = make_vcr("lan")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skip_if_no_cassette(subdir: str, name: str):
    """pytest.mark.skipif that fires when cassette is absent and not recording."""
    recording = os.environ.get("VCR_RECORD_MODE", "none") not in ("none", "")
    return pytest.mark.skipif(
        not cassette_exists(subdir, name) and not recording,
        reason=f"cassette {subdir}/{name}.yaml not recorded yet; "
               f"run with VCR_RECORD_MODE=all to record",
    )


def _clear_pwb_site_cache() -> None:
    """Clear pywikibot's in-process site cache so each test initialises fresh."""
    try:
        import pywikibot.site as _pws

        for attr in ("_sites", "_iw_sites"):
            cache = getattr(_pws.BaseSite, attr, None)
            if isinstance(cache, dict):
                cache.clear()
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def pwb_clean_slate():
    _clear_pwb_site_cache()
    yield
    _clear_pwb_site_cache()


# ---------------------------------------------------------------------------
# en.wikisource.org — public wiki, cassettes committable to the repo
# ---------------------------------------------------------------------------

_EN_SETTINGS = WikiSettings(family="wikisource", code="en")

_en_index = _skip_if_no_cassette("en_ws", "get_index_page")
_en_file_info = _skip_if_no_cassette("en_ws", "get_file_info")
_en_page_1 = _skip_if_no_cassette("en_ws", "get_page_1")
_en_fanout = _skip_if_no_cassette("en_ws", "fanout_index")


@_en_index
def test_en_ws_get_index_page():
    """Index: page has the right content_model, a <pagelist>, and page_count from IndexPage."""
    with _EN_VCR.use_cassette("get_index_page.yaml"):
        client = PywikibotClient(_EN_SETTINGS)
        remote = client.get_page(TRACTATUS_INDEX)

    assert remote.content_model == "proofread-index"
    assert remote.namespace_canonical == "Index"
    assert remote.revid is not None
    assert remote.sha1 is not None
    assert "<pagelist" in (remote.text or "")
    # page_count comes from IndexPage.num_pages, not <pagelist> parsing.
    assert remote.page_count is not None
    assert 100 < remote.page_count < 300


@_en_file_info
def test_en_ws_get_file_info():
    """File: imageinfo returns real sha1, size, and mime for the DjVu blob."""
    with _EN_VCR.use_cassette("get_file_info.yaml"):
        client = PywikibotClient(_EN_SETTINGS)
        info = client.get_file_info(TRACTATUS_FILE)

    assert info.mime == "image/vnd.djvu"
    assert info.size > 0
    assert len(info.file_sha1) == 40
    # page_count is not asserted here: it comes from IndexPage.num_pages (via
    # get_page), not from imageinfo metadata, which is absent for many file types.


@_en_page_1
def test_en_ws_get_page_1():
    """Page:...djvu/1 is a proofread-page with wikitext body."""
    with _EN_VCR.use_cassette("get_page_1.yaml"):
        client = PywikibotClient(_EN_SETTINGS)
        remote = client.get_page(TRACTATUS_PAGE_1)

    assert remote.content_model == "proofread-page"
    assert remote.namespace_canonical == "Page"
    assert remote.revid is not None


@_en_fanout
def test_en_ws_fanout_index(engine, tmp_path):
    """Full worker integration: POST /fetch with depth=1 fans out all pages.

    Uses the cassette that covers the index fetch + file info + all page fetches.
    The DjVu binary is stubbed in the cassette; metadata assertions still pass.
    """
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select

    from wtbot.main import create_app
    from wtbot.wiki.client import PywikibotClient

    with _EN_VCR.use_cassette("fanout_index.yaml"):
        app = create_app(
            engine=engine,
            client_factory=lambda site: PywikibotClient(_EN_SETTINGS),
            blob_root=tmp_path / "blobs",
        )
        with TestClient(app) as http:
            resp = http.post(
                "/fetch/",
                json={
                    "title": TRACTATUS_INDEX,
                    "family": "wikisource",
                    "code": "en",
                    "depth": 1,
                },
            )

    assert resp.status_code == 202
    body = resp.json()
    assert body["request"]["status"] == FetchStatus.done.value

    index_page = body["page"]
    assert index_page["content_model"] == "proofread-index"
    assert index_page["page_count"] is not None and index_page["page_count"] > 0

    with Session(engine) as s:
        all_pages = s.exec(select(Page)).all()
        # index + all page children
        assert len(all_pages) == 1 + index_page["page_count"]

        idx = next(p for p in all_pages if p.title == TRACTATUS_INDEX)
        fb = s.exec(select(FileBlob).where(FileBlob.page_pk == idx.pk)).first()
        assert fb is not None
        assert fb.mime == "image/vnd.djvu"
        assert len(fb.file_sha1) == 40


# ---------------------------------------------------------------------------
# wikisource-debian-13.lan — local wiki, needs WTBOT_WIKI_CA_BUNDLE to record
# ---------------------------------------------------------------------------

_LAN_API = "https://wikisource-debian-13.lan/w/api.php"
_LAN_CA = os.environ.get("WTBOT_WIKI_CA_BUNDLE")
_LAN_SETTINGS = WikiSettings(
    family="mywikisource",
    code="en",
    api_url=_LAN_API,
    ca_bundle=_LAN_CA,
)

_lan_index = _skip_if_no_cassette("lan", "get_index_page")
_lan_file_info = _skip_if_no_cassette("lan", "get_file_info")
_lan_page_1 = _skip_if_no_cassette("lan", "get_page_1")
_lan_fanout = _skip_if_no_cassette("lan", "fanout_index")


@_lan_index
def test_lan_get_index_page():
    """Same Index: title on the local wiki — including page_count from IndexPage."""
    with _LAN_VCR.use_cassette("get_index_page.yaml"):
        client = PywikibotClient(_LAN_SETTINGS)
        remote = client.get_page(TRACTATUS_INDEX)

    assert remote.content_model == "proofread-index"
    assert remote.namespace_canonical == "Index"
    assert remote.revid is not None
    assert "<pagelist" in (remote.text or "")
    assert remote.page_count is not None
    assert 100 < remote.page_count < 300


@_lan_file_info
def test_lan_get_file_info():
    """File: imageinfo on local wiki — sha1 should match en.ws if same file."""
    with _LAN_VCR.use_cassette("get_file_info.yaml"):
        client = PywikibotClient(_LAN_SETTINGS)
        info = client.get_file_info(TRACTATUS_FILE)

    assert info.mime == "image/vnd.djvu"
    assert info.size > 0
    assert len(info.file_sha1) == 40


@_lan_page_1
def test_lan_get_page_1():
    """Page 1 on local wiki is a proofread-page."""
    with _LAN_VCR.use_cassette("get_page_1.yaml"):
        client = PywikibotClient(_LAN_SETTINGS)
        remote = client.get_page(TRACTATUS_PAGE_1)

    assert remote.content_model == "proofread-page"
    assert remote.revid is not None


@_lan_fanout
def test_lan_fanout_index(engine, tmp_path):
    """Full worker integration on the local wiki."""
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select

    from wtbot.main import create_app

    with _LAN_VCR.use_cassette("fanout_index.yaml"):
        app = create_app(
            engine=engine,
            client_factory=lambda site: PywikibotClient(_LAN_SETTINGS),
            blob_root=tmp_path / "blobs",
        )
        with TestClient(app) as http:
            resp = http.post(
                "/fetch/",
                json={
                    "title": TRACTATUS_INDEX,
                    "family": "mywikisource",
                    "code": "en",
                    "api_url": _LAN_API,
                    "depth": 1,
                },
            )

    assert resp.status_code == 202
    body = resp.json()
    assert body["request"]["status"] == FetchStatus.done.value

    index_page = body["page"]
    assert index_page["content_model"] == "proofread-index"
    assert index_page["page_count"] is not None and index_page["page_count"] > 0

    with Session(engine) as s:
        all_pages = s.exec(select(Page)).all()
        assert len(all_pages) == 1 + index_page["page_count"]

        idx = next(p for p in all_pages if p.title == TRACTATUS_INDEX)
        fb = s.exec(select(FileBlob).where(FileBlob.page_pk == idx.pk)).first()
        assert fb is not None
        assert fb.mime == "image/vnd.djvu"
