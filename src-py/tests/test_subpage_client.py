from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import FAKE_TIMESTAMP, fake_pageid

from wtbot.wiki.client import FakeWikiClient, PywikibotClient
from wtbot.wiki.wiki_types import RemotePage


@pytest.mark.parametrize("namespace_key", [0, 252, 3000])
def test_subpage_query_uses_normalized_title_and_site_namespace(
    monkeypatch, namespace_key
):
    from pywikibot import pagegenerators

    parent = Mock()
    parent.title.return_value = "Localized:A work"
    parent.namespace.return_value = SimpleNamespace(id=namespace_key)
    child = Mock()
    child.title.return_value = "Localized:A work/Part 1/Chapter 1"
    generator = Mock(return_value=iter([child]))
    monkeypatch.setattr(pagegenerators, "PrefixingPageGenerator", generator)
    client = PywikibotClient.__new__(PywikibotClient)
    client.site = Mock()
    client._pwb = SimpleNamespace(Page=Mock(return_value=parent))

    assert client.list_subpage_titles("Localized:A_work") == [child.title()]
    generator.assert_called_once_with(
        prefix="Localized:A work/", site=client.site, namespace=namespace_key
    )


def test_fake_subpage_query_matches_spaces_and_underscores():
    titles = [
        "Book:A work/Part 1",
        "Book:A_work/Part_1/Chapter_1",
        "Book:A work extra/Notes",
        "Book:A work",
    ]
    client = FakeWikiClient(
        pages={
            title: RemotePage(
                title=title,
                namespace_key=3000,
                namespace_canonical="Book",
                content_model="wikitext",
                text="body",
                pageid=fake_pageid(title),
                revid=fake_pageid(title),
                timestamp=FAKE_TIMESTAMP,
            )
            for title in titles
        }
    )
    for spelling in ["Book:A work", "Book:A_work"]:
        assert client.list_subpage_titles(spelling) == sorted(titles[:2])
