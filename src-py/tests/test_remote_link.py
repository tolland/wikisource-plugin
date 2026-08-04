from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from wtbot.model import LinkOrigin, Page, RemoteLink, Revision, Site
from wtbot.remote_link_store import (
    LinkError,
    assert_link,
    corresponding_page,
    current_anchor,
    find_link,
    ladder,
    links_for_revision,
)
from wtbot.revision_store import record_head_revision
from wtbot.wiki.wiki_types import RemotePage

"""Asserted correspondence between revisions on two sites.

The thing under test is a *claim*, not a computation. These tests deliberately
link revisions whose content differs and revisions whose content is identical,
and expect the same outcome from both: a proofread-page body embeds a
site-specific ``pagequality user=``, so hash agreement is neither necessary nor
sufficient for correspondence (docs/upstream-sync-discussion.md section 3).
"""

PROOFREAD = "proofread-page"
TITLE = "Page:The varieties of religious experience.djvu/12"


def _site(session: Session, family: str) -> Site:
    site = Site(family=family, code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def _revision(
    session: Session, site: Site, title: str, *, revid: int, body: str
) -> Revision:
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()
    if page is None:
        page = Page(site_pk=site.pk, title=title)
        session.add(page)
        session.commit()
        session.refresh(page)

    remote = RemotePage(
        title=title,
        namespace_key=104,
        namespace_canonical="Page",
        content_model=PROOFREAD,
        text=body,
        revid=revid,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    revision = record_head_revision(session, page, remote)
    session.commit()
    assert revision is not None
    return revision


def _body(level: int, user: str) -> str:
    return (
        f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>'
        "The Varieties of Religious Experience."
    )


@pytest.fixture
def pair(session: Session) -> tuple[Revision, Revision]:
    """One page on each of two sites, transcribed the same but attributed
    differently -- the cross-site norm, and the case hashes get wrong."""
    upstream = _site(session, "wikisource")
    local = _site(session, "mywikisource")
    return (
        _revision(session, local, TITLE, revid=3, body=_body(3, "LocalEditor")),
        _revision(session, upstream, TITLE, revid=8814, body=_body(1, "Hesperian")),
    )


def test_a_link_is_recorded_despite_differing_hashes(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    local, remote = pair
    link = assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    assert link.pk is not None
    assert link.origin is LinkOrigin.copy
    assert session.exec(select(RemoteLink)).all() == [link]


def test_re_asserting_a_pair_keeps_the_original_row(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """Idempotent on the pair, and the first origin wins: re-stating a known
    correspondence is not new information, and overwriting the origin would
    rewrite history in an append-only table."""
    local, remote = pair
    first = assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()
    second = assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.manual,
    )
    session.commit()

    assert first.pk == second.pk
    assert second.origin is LinkOrigin.copy
    assert len(session.exec(select(RemoteLink)).all()) == 1


def test_the_same_link_reversed_is_the_same_link(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """Neither side is privileged. "A corresponds to B" and "B corresponds to
    A" are one fact, so asserting it the other way round must return the row
    already there rather than adding a second."""
    local, remote = pair
    first = assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    reversed_assertion = assert_link(
        session,
        local_revision_pk=remote.pk,
        remote_revision_pk=local.pk,
        origin=LinkOrigin.manual,
    )
    session.commit()

    assert reversed_assertion.pk == first.pk
    assert reversed_assertion.origin is LinkOrigin.copy
    assert len(session.exec(select(RemoteLink)).all()) == 1


def test_the_database_itself_rejects_a_reversed_duplicate(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """The store is not the only thing that can write this table, so the
    guarantee cannot live only in the store. A raw insert bypassing
    ``assert_link`` must still fail."""
    local, remote = pair
    assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    session.add(
        RemoteLink(
            local_revision_pk=remote.pk,
            remote_revision_pk=local.pk,
            origin=LinkOrigin.manual,
        )
    )
    with pytest.raises(IntegrityError, match="uq_remotelink_pair"):
        session.commit()
    session.rollback()


def test_a_reversed_link_is_found_from_either_orientation(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """A pair asserted one way must be readable the other way, or a page pair
    silently grows a second, empty ladder."""
    local, remote = pair
    link = assert_link(
        session,
        local_revision_pk=remote.pk,
        remote_revision_pk=local.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    forward = ladder(session, page_pk=local.page_pk, other_page_pk=remote.page_pk)
    backward = ladder(session, page_pk=remote.page_pk, other_page_pk=local.page_pk)

    assert forward == backward == [link]
    assert (
        current_anchor(session, page_pk=local.page_pk, other_page_pk=remote.page_pk).pk
        == link.pk
    )
    assert (
        find_link(session, revision_pk=local.pk, other_revision_pk=remote.pk).pk
        == link.pk
    )


def test_two_revisions_of_the_same_site_cannot_be_linked(session: Session) -> None:
    """Within one wiki, ancestry already says everything a link would."""
    site = _site(session, "mywikisource")
    first = _revision(session, site, TITLE, revid=3, body=_body(1, "A"))
    second = _revision(session, site, TITLE, revid=4, body=_body(3, "A"))

    with pytest.raises(LinkError, match="across sites"):
        assert_link(
            session,
            local_revision_pk=first.pk,
            remote_revision_pk=second.pk,
            origin=LinkOrigin.manual,
        )


def test_a_revision_cannot_be_linked_to_itself(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    local, _ = pair
    with pytest.raises(LinkError, match="itself"):
        assert_link(
            session,
            local_revision_pk=local.pk,
            remote_revision_pk=local.pk,
            origin=LinkOrigin.manual,
        )


def test_an_unknown_revision_is_refused(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    local, _ = pair
    with pytest.raises(LinkError, match="no revision with pk"):
        assert_link(
            session,
            local_revision_pk=local.pk,
            remote_revision_pk=9999,
            origin=LinkOrigin.manual,
        )


def test_the_ladder_grows_and_the_last_rung_is_the_anchor(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """Re-anchoring is forward-only. Remote history is append-only -- no rebase,
    no discoverable merge base -- so a human making the two sides identical
    appends a `reconciled` rung rather than editing the broken one."""
    local, remote = pair
    upstream_site_pk = session.get(Page, remote.page_pk).site_pk
    local_site_pk = session.get(Page, local.page_pk).site_pk

    assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    # Both sides move on, then a human reconciles them.
    local_page = session.get(Page, local.page_pk)
    remote_page = session.get(Page, remote.page_pk)
    local_next = _revision(
        session,
        session.get(Site, local_site_pk),
        local_page.title,
        revid=9,
        body=_body(3, "LocalEditor"),
    )
    remote_next = _revision(
        session,
        session.get(Site, upstream_site_pk),
        remote_page.title,
        revid=8900,
        body=_body(3, "Hesperian"),
    )
    reconciled = assert_link(
        session,
        local_revision_pk=local_next.pk,
        remote_revision_pk=remote_next.pk,
        origin=LinkOrigin.reconciled,
    )
    session.commit()

    rungs = ladder(session, page_pk=local.page_pk, other_page_pk=remote.page_pk)
    assert [rung.origin for rung in rungs] == [
        LinkOrigin.copy,
        LinkOrigin.reconciled,
    ]
    anchor = current_anchor(
        session, page_pk=local.page_pk, other_page_pk=remote.page_pk
    )
    assert anchor.pk == reconciled.pk
    assert anchor.local_revision_pk == local_next.pk


def test_an_unlinked_pair_has_no_anchor(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    local, remote = pair
    assert (
        current_anchor(session, page_pk=local.page_pk, other_page_pk=remote.page_pk)
        is None
    )


def test_page_correspondence_is_derived_in_both_directions(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """No page-pair table: the correspondence is read off the links, and it
    answers from either end regardless of which side was called 'local'."""
    local, remote = pair
    assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.copy,
    )
    session.commit()

    local_page = session.get(Page, local.page_pk)
    remote_page = session.get(Page, remote.page_pk)

    assert (
        corresponding_page(
            session, page_pk=local.page_pk, other_site_pk=remote_page.site_pk
        ).pk
        == remote_page.pk
    )
    assert (
        corresponding_page(
            session, page_pk=remote.page_pk, other_site_pk=local_page.site_pk
        ).pk
        == local_page.pk
    )


def test_a_redlink_target_has_no_correspondence(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    """A page that does not exist on the other side must have no link, not a
    link to nothing: there is nothing to compare, and whether it *should* exist
    is a pairing question this table does not answer."""
    local, remote = pair
    remote_site_pk = session.get(Page, remote.page_pk).site_pk
    orphan = _revision(
        session,
        session.get(Site, session.get(Page, local.page_pk).site_pk),
        "Page:The varieties of religious experience.djvu/13",
        revid=4,
        body=_body(1, "LocalEditor"),
    )

    assert (
        corresponding_page(
            session, page_pk=orphan.page_pk, other_site_pk=remote_site_pk
        )
        is None
    )


def test_links_are_found_from_either_end_of_a_revision(
    session: Session, pair: tuple[Revision, Revision]
) -> None:
    local, remote = pair
    link = assert_link(
        session,
        local_revision_pk=local.pk,
        remote_revision_pk=remote.pk,
        origin=LinkOrigin.title_match,
    )
    session.commit()

    assert links_for_revision(session, local.pk) == [link]
    assert links_for_revision(session, remote.pk) == [link]
