"""Expired login handshakes get one retry, never an unbounded drain loop."""

from unittest.mock import Mock

import pytest
from sqlmodel import Session, select

from wtbot.fetch.queue_runner import drain_queue
from wtbot.model import FetchRequest, FetchStatus, Site
from wtbot.wiki.client import PywikibotClient
from wtbot.wiki.failures import FailureKind, classify
from wtbot.wiki.wiki_types import RemotePage


class NoUsernameError(Exception):
    pass


def timeout() -> NoUsernameError:
    return NoUsernameError(
        "Failed on mywikisource: Unable to continue login. "
        "Your session most likely timed out."
    )


def client_with_site() -> PywikibotClient:
    client = PywikibotClient.__new__(PywikibotClient)
    client.site = Mock()
    return client


@pytest.mark.parametrize("stage", ["page", "revision"])
def test_fetch_retries_login_timeout_during_page_or_revision_load(stage):
    client = client_with_site()
    remote = object()
    client._pwb = Mock()
    client._pwb.exceptions.NoPageError = type("NoPageError", (Exception,), {})
    client._pwb.exceptions.InvalidPageError = type("InvalidPageError", (Exception,), {})

    class ExpiredPage:
        @property
        def latest_revision(self):
            raise timeout()

    # First attempt executes the real get_page implementation at the failing
    # boundary. The second returns a sentinel so no enrichment setup is needed.
    original = client._get_page
    calls = 0

    def read(title):
        nonlocal calls
        calls += 1
        return original(title) if calls == 1 else remote

    client._get_page = Mock(side_effect=read)
    if stage == "page":
        client._pwb.Page.side_effect = timeout()
    else:
        client._pwb.Page.return_value = ExpiredPage()

    assert client.get_page("Title") is remote
    assert calls == 2
    client.site.tokens.clear.assert_called_once_with()
    client.site._relogin.assert_called_once_with()


@pytest.mark.parametrize("fails_in_relogin", [False, True])
def test_persistent_timeout_is_bounded(fails_in_relogin):
    client = client_with_site()
    client._get_page = Mock(side_effect=timeout())
    if fails_in_relogin:
        client.site._relogin.side_effect = timeout()
    with pytest.raises(NoUsernameError):
        client.get_page("Title")
    assert client._get_page.call_count == (1 if fails_in_relogin else 2)
    client.site._relogin.assert_called_once_with()


def test_bad_credentials_are_not_retried():
    client = client_with_site()
    client._get_page = Mock(side_effect=NoUsernameError("Incorrect password"))
    with pytest.raises(NoUsernameError):
        client.get_page("Title")
    client._get_page.assert_called_once_with("Title")
    client.site._relogin.assert_not_called()


def test_timeout_is_classified_as_transient():
    failure = classify(timeout())
    assert failure.kind is FailureKind.session_expired
    assert failure.transient
    assert not classify(NoUsernameError("Incorrect password")).transient


@pytest.mark.parametrize("persistent", [False, True])
def test_drain_records_terminal_status_after_login_recovery(engine, persistent):
    client = client_with_site()
    client.site.namespaces = None
    remote = RemotePage(
        title="Title",
        namespace_key=0,
        namespace_canonical="",
        content_model="wikitext",
        text="body",
        revid=1,
    )
    client._get_page = Mock(
        side_effect=[timeout(), timeout() if persistent else remote]
    )
    with Session(engine) as session:
        site = Site(family="test", code="en")
        session.add(site)
        session.commit()
        session.add(FetchRequest(site_pk=site.pk, title="Title"))
        session.commit()

        result = drain_queue(session, lambda _: client)

        assert result.handled == 1
        assert result.remaining == 0
        request = session.exec(select(FetchRequest)).one()
        assert request.status is (FetchStatus.error if persistent else FetchStatus.done)
        if persistent:
            assert "session most likely timed out" in request.error_message
