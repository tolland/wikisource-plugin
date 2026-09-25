"""Shared file descriptions must not become local revision identities."""

from unittest.mock import Mock, PropertyMock

import pytest

from wtbot.wiki.client import PywikibotClient
from wtbot.wiki.wiki_types import PageNotFound


class MissingPage(Exception):
    pass


class InvalidPage(Exception):
    pass


@pytest.fixture
def shared_client():
    client = PywikibotClient.__new__(PywikibotClient)
    client.site = Mock()
    client._pwb = Mock()
    client._pwb.exceptions.NoPageError = MissingPage
    client._pwb.exceptions.InvalidPageError = InvalidPage
    local = Mock()
    local.title.return_value = "File:Shared scan.pdf"
    local.namespace.return_value.id = 6
    local.exists.return_value = False
    type(local).latest_revision = PropertyMock(side_effect=MissingPage)
    client._pwb.Page.return_value = local
    shared = Mock()
    shared.exists.return_value = True
    shared.content_model = "wikitext"
    shared.latest_revision.text = "Commons description"
    shared.latest_revision.revid = 12345
    shared.pageid = 6789
    client._pwb.FilePage.side_effect = lambda site, title: (
        local if site is client.site else shared
    )
    return client, local, shared


def test_shared_description_is_fetched_without_local_revision_ids(shared_client):
    client, _, _ = shared_client
    remote = client.get_page("File:Shared_scan.pdf")
    assert remote.title == "File:Shared scan.pdf"
    assert remote.namespace_key == 6
    assert remote.text == "Commons description"
    assert remote.pageid is None
    assert remote.revid is None
    assert remote.parentid is None
    assert client.get_history(remote.title, limit=14) == []


def test_batch_fetch_also_follows_shared_repository(shared_client):
    client, local, _ = shared_client
    client.site.preloadpages.return_value = [local]
    results = client.get_pages(["File:Shared_scan.pdf"])
    assert results[0].title == "File:Shared_scan.pdf"
    assert results[0].result.text == "Commons description"
    assert results[0].result.pageid is None
    assert results[0].result.revid is None


@pytest.mark.parametrize("operation", ["page", "history"])
def test_file_missing_on_both_sites_still_fails(shared_client, operation):
    client, _, shared = shared_client
    shared.exists.return_value = False
    with pytest.raises(PageNotFound):
        if operation == "page":
            client.get_page("File:Shared scan.pdf")
        else:
            client.get_history("File:Shared scan.pdf", limit=14)


def test_missing_non_file_does_not_fall_back_to_commons(shared_client):
    client, local, _ = shared_client
    local.namespace.return_value.id = 0
    with pytest.raises(PageNotFound):
        client.get_page("Missing article")
    client._pwb.FilePage.assert_not_called()


def test_local_file_description_keeps_its_revision(shared_client):
    client, local, _ = shared_client
    revision = Mock(
        text="Local description",
        revid=42,
        parentid=41,
        timestamp=None,
        user="editor",
        comment="edit",
        sha1="abc",
        size=17,
    )
    type(local).latest_revision = PropertyMock(return_value=revision)
    local.content_model = "wikitext"
    local.pageid = 12
    local.namespace.return_value.canonical_name = "File"
    remote = client.get_page("File:Shared scan.pdf")
    assert remote.text == "Local description"
    assert remote.pageid == 12
    assert remote.revid == 42
    client._pwb.FilePage.assert_not_called()
