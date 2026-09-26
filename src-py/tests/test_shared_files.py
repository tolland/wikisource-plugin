from unittest.mock import Mock, PropertyMock

import pytest

from wtbot.wiki.client import PywikibotClient
from wtbot.wiki.wiki_types import FileIsShared, PageNotFound

"""A File: served from the shared repository is not this wiki's page.

The client reports it as shared -- on the local wiki's own word,
``imagerepository`` -- rather than borrowing Commons's description under a
local title with no ids. The fetch worker then fetches the page on the
repository's registered site (see test_shared_repository).
"""


class MissingPage(Exception):
    pass


class InvalidPage(Exception):
    pass


def _imageinfo(repository: str) -> dict:
    return {"query": {"pages": {"-1": {"imagerepository": repository}}}}


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
    client._pwb.FilePage.return_value = local
    client._api_query = Mock(return_value=_imageinfo("shared"))
    return client, local


@pytest.mark.parametrize("operation", ["page", "history"])
def test_a_shared_file_is_reported_as_shared(shared_client, operation):
    client, _ = shared_client
    with pytest.raises(FileIsShared) as raised:
        if operation == "page":
            client.get_page("File:Shared_scan.pdf")
        else:
            client.get_history("File:Shared_scan.pdf", limit=14)
    assert raised.value.title == "File:Shared scan.pdf"


def test_batch_fetch_reports_it_too(shared_client):
    client, local = shared_client
    client.site.preloadpages.return_value = [local]
    [result] = client.get_pages(["File:Shared_scan.pdf"])
    assert isinstance(result.result, FileIsShared)


@pytest.mark.parametrize("operation", ["page", "history"])
def test_file_missing_everywhere_is_not_found(shared_client, operation):
    client, _ = shared_client
    client._api_query.return_value = _imageinfo("")
    with pytest.raises(PageNotFound):
        if operation == "page":
            client.get_page("File:Shared scan.pdf")
        else:
            client.get_history("File:Shared scan.pdf", limit=14)


def test_a_missing_non_file_asks_nothing_about_repositories(shared_client):
    client, local = shared_client
    local.namespace.return_value.id = 0
    with pytest.raises(PageNotFound):
        client.get_page("Missing article")
    client._api_query.assert_not_called()


def test_local_file_description_keeps_its_revision(shared_client):
    client, local = shared_client
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
    client._api_query.assert_not_called()
