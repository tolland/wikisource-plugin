"""Exercise Pywikibot's real preload generator without HTTP."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from wtbot.wiki.client import PywikibotClient
from wtbot.wiki.wiki_types import PageNotFound


class MissingPage(Exception):
    pass


class InvalidPage(Exception):
    pass


class PreloadedPage:
    def __init__(self, site, title):
        self._title = title.replace("_", " ")
        self.loaded = False

    def title(self, **kwargs):
        if self._title == "[invalid]":
            raise InvalidPage()
        return self._title

    def exists(self):
        assert self.loaded, "existence must come from the bulk response"
        return self._title != "missing"

    def namespace(self):
        return SimpleNamespace(id=0, canonical_name="")

    @property
    def latest_revision(self):
        assert self.loaded, "revision must come from the bulk response"
        return SimpleNamespace(
            text=f"body {self._title}",
            revid=42,
            parentid=41,
            timestamp=None,
            user="editor",
            comment="",
            sha1="abc",
            size=10,
        )


@pytest.fixture
def bulk_client(monkeypatch):
    from pywikibot.data import api
    from pywikibot.site import APISite

    calls = []

    class Generator:
        def __init__(self, props, site):
            self.props = props
            self.request = {}

        def set_maximum_items(self, value):
            assert value == -1  # no rvlimit for multiple titles

        def __iter__(self):
            calls.append(self.request.copy())
            for title in reversed(self.request["titles"]):
                yield {"title": title}

    def update_page(page, data, props):
        assert "revisions" in props and "info" in props
        page.loaded = True
        page.content_model = "wikitext"
        page.pageid = 7

    monkeypatch.setattr(api, "PropertyGenerator", Generator)
    monkeypatch.setattr(api, "update_page", update_page)
    client = PywikibotClient.__new__(PywikibotClient)
    client.site = Mock(maxlimit=500)
    client.site._rvprops.return_value = "ids|timestamp|user|comment|sha1|size|content"
    client.site.preloadpages = MethodType(APISite.preloadpages, client.site)
    client._pwb = SimpleNamespace(
        Page=PreloadedPage,
        exceptions=SimpleNamespace(
            NoPageError=MissingPage, InvalidPageError=InvalidPage
        ),
    )
    return client, calls


def test_real_preloader_batches_at_50_and_reads_cached_revisions(bulk_client):
    client, calls = bulk_client
    titles = [f"Article {n}" for n in range(121)]
    results = client.get_pages(titles)
    assert [len(call["titles"]) for call in calls] == [50, 50, 21]
    assert [result.title for result in results] == titles
    assert [result.result.text for result in results] == [
        f"body {title}" for title in titles
    ]


def test_normalized_duplicate_missing_invalid_and_redirect_titles(bulk_client):
    client, calls = bulk_client
    titles = ["An_article", "missing", "An article", "[invalid]", "Redirect"]
    results = client.get_pages(titles)
    assert len(calls) == 1
    assert calls[0]["titles"] == ["An article", "missing", "Redirect"]
    assert [result.title for result in results] == titles
    assert results[0].result.title == "An article"
    assert isinstance(results[1].result, PageNotFound)
    assert results[2].result.text == "body An article"
    assert isinstance(results[3].result, InvalidPage)
    assert results[4].result.title == "Redirect"
    assert "redirects" not in calls[0]


def test_bulk_transport_failure_propagates_without_serial_fallback(bulk_client):
    client, _ = bulk_client
    client.site.preloadpages = Mock(side_effect=RuntimeError("network failure"))
    with pytest.raises(RuntimeError, match="network failure"):
        client.get_pages(["one", "two"])
