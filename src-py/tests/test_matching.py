from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.content_model import Significance
from wtbot.matching import (
    MatchOutcome,
    compare_pages,
    confirm_proposals,
    propose_index_links,
)
from wtbot.model import LinkOrigin, NsRole, Page, PageMeta, RemoteLink, Site
from wtbot.remote_link_store import assert_link, current_anchor
from wtbot.revision_store import record_head_revision
from wtbot.wiki.wiki_types import RemotePage

"""Proposing correspondences, and the ambiguity it deliberately avoids.

A run of touch edits leaves several byte-identical revisions with nothing to
choose between them, so "find the revision matching ours" has no single answer.
Matching therefore compares *heads*, where each side has exactly one -- see the
module docstring of wtbot.matching for why a historical base is not wanted in
the first place.
"""

INDEX = "Index:Canadian patent 29537.djvu"
PROOFREAD = "proofread-page"


def _site(session: Session, family: str) -> Site:
    site = Site(family=family, code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def _body(level: int, user: str, text: str = "The transcription.") -> str:
    return f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>{text}'


def _page(
    session: Session,
    site: Site,
    number: int,
    *,
    body: str | None,
    revid: int,
    index_title: str = INDEX,
    title: str | None = None,
) -> Page:
    title = title or f"Page:Canadian patent 29537.djvu/{number}"
    page = Page(site_pk=site.pk, title=title, namespace_role=NsRole.page)
    session.add(page)
    session.commit()
    session.refresh(page)
    session.add(PageMeta(page_pk=page.pk, index_title=index_title, page_number=number))
    session.commit()

    if body is not None:
        record_head_revision(
            session,
            page,
            RemotePage(
                title=title,
                namespace_key=104,
                namespace_canonical="Page",
                content_model=PROOFREAD,
                text=body,
                revid=revid,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        session.commit()
    return page


def test_the_same_transcription_under_different_attribution_is_proposable(
    session: Session,
) -> None:
    """The cross-site norm: identical words, a username that exists on one wiki
    only. Byte equality would reject this; the content model does not."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "LocalEditor"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(3, "Hesperian"), revid=900)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.same
    assert proposal.significance is Significance.metadata_only
    assert proposal.proposable


def test_a_differing_quality_level_is_surfaced_not_folded_in(
    session: Session,
) -> None:
    """Same words, different proofreading state. Proposable, but the level is
    directional -- pushing 2 over someone's 4 discards an assessment -- so it
    must not arrive looking like an ordinary match."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(2, "LocalEditor"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(4, "Hesperian"), revid=900)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.quality_differs
    assert proposal.proposable


def test_diverged_transcriptions_are_not_proposable(session: Session) -> None:
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "A", "Our words."), revid=5)
    remote_page = _page(
        session, remote, 1, body=_body(3, "B", "Their words."), revid=900
    )

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.diverged
    assert not proposal.proposable


def test_a_run_of_identical_revisions_does_not_make_the_match_ambiguous(
    session: Session,
) -> None:
    """The touch-edit case.

    Three consecutive remote revisions hold byte-identical content -- exactly
    what a `Pywikibot touch edit` campaign leaves behind -- so "which revision
    matches ours" has three equally true answers. Matching compares heads, so
    the question never arises: the answer is the head, and it is stable across
    repeated runs.
    """
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "LocalEditor"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(3, "Hesperian"), revid=900)

    # Two further revisions, same content, as touch edits produce.
    for revid in (901, 902):
        record_head_revision(
            session,
            remote_page,
            RemotePage(
                title=remote_page.title,
                namespace_key=104,
                namespace_canonical="Page",
                content_model=PROOFREAD,
                text=_body(3, "Hesperian"),
                revid=revid,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        session.commit()

    first = compare_pages(session, local_page, remote_page)
    second = compare_pages(session, local_page, remote_page)

    assert first.remote_revid == second.remote_revid == 902
    assert first.outcome is MatchOutcome.same


def test_an_uncached_side_is_a_fetch_not_a_verdict(session: Session) -> None:
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "A"), revid=5)
    remote_page = _page(session, remote, 1, body=None, revid=0)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.unfetched
    assert not proposal.proposable


def test_a_missing_counterpart_has_no_link(session: Session) -> None:
    local = _site(session, "mywikisource")
    local_page = _page(session, local, 1, body=_body(3, "A"), revid=5)

    proposal = compare_pages(session, local_page, None)

    assert proposal.outcome is MatchOutcome.no_counterpart


def test_an_index_fans_out_and_pairs_on_page_number(session: Session) -> None:
    """Titles can differ between the sides -- that is what `--to` is for -- so
    the structural key is the page number within the index."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    for number in (1, 2, 3):
        _page(session, local, number, body=_body(3, "LocalEditor"), revid=number)
    for number in (1, 2):
        _page(
            session,
            remote,
            number,
            body=_body(3, "Hesperian"),
            revid=900 + number,
            index_title="Index:Patent (upstream).djvu",
            title=f"Page:Patent (upstream).djvu/{number}",
        )

    proposals = propose_index_links(
        session,
        local_site=local,
        remote_site=remote,
        local_index_title=INDEX,
        remote_index_title="Index:Patent (upstream).djvu",
    )

    assert [p.page_number for p in proposals] == [1, 2, 3]
    assert [p.outcome for p in proposals] == [
        MatchOutcome.same,
        MatchOutcome.same,
        MatchOutcome.no_counterpart,
    ]
    assert proposals[0].remote_title == "Page:Patent (upstream).djvu/1"


def test_an_already_linked_pair_is_reported_not_proposed_again(
    session: Session,
) -> None:
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "A"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(3, "B"), revid=900)

    first = compare_pages(session, local_page, remote_page)
    confirm_proposals(session, [first], origin=LinkOrigin.copy)
    session.commit()

    again = compare_pages(session, local_page, remote_page)

    assert again.outcome is MatchOutcome.already_linked
    assert not again.proposable
    assert "copy" in again.detail


def test_confirming_writes_links_and_refuses_the_unproposable(
    session: Session,
) -> None:
    """`confirm_proposals` never filters for the caller: silently skipping the
    unproposable is how "confirm everything that looked fine" creeps in."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "A"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(3, "B"), revid=900)
    diverged_local = _page(session, local, 2, body=_body(3, "A", "Ours."), revid=6)
    diverged_remote = _page(
        session, remote, 2, body=_body(3, "B", "Theirs."), revid=901
    )

    good = compare_pages(session, local_page, remote_page)
    bad = compare_pages(session, diverged_local, diverged_remote)

    confirm_proposals(session, [good], origin=LinkOrigin.title_match)
    session.commit()

    assert len(session.exec(select(RemoteLink)).all()) == 1
    anchor = current_anchor(
        session, page_pk=local_page.pk, other_page_pk=remote_page.pk
    )
    assert anchor.origin is LinkOrigin.title_match

    try:
        confirm_proposals(session, [bad])
        raise AssertionError("a diverged proposal must not be confirmable")
    except ValueError as exc:
        assert "diverged" in str(exc)


def test_the_propose_endpoint_writes_nothing_by_default(client, engine) -> None:
    with Session(engine) as session:
        local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
        _page(session, local, 1, body=_body(3, "LocalEditor"), revid=5)
        _page(session, remote, 1, body=_body(3, "Hesperian"), revid=900)

    body = {
        "local": {"family": "mywikisource", "code": "en"},
        "remote": {"family": "wikisource", "code": "en"},
        "index_title": INDEX,
    }
    response = client.post("/links/propose", json=body)

    assert response.status_code == 200
    assert response.json()["counts"] == {"same": 1}
    assert response.json()["confirmed"] == 0
    with Session(engine) as session:
        assert session.exec(select(RemoteLink)).all() == []

    confirmed = client.post("/links/propose", json={**body, "confirm": True})
    assert confirmed.json()["confirmed"] == 1
    with Session(engine) as session:
        assert len(session.exec(select(RemoteLink)).all()) == 1


def test_linking_a_diverged_pair_needs_force(client, engine) -> None:
    with Session(engine) as session:
        local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
        _page(session, local, 1, body=_body(3, "A", "Ours."), revid=5)
        _page(session, remote, 1, body=_body(3, "B", "Theirs."), revid=900)

    body = {
        "local": {"family": "mywikisource", "code": "en"},
        "remote": {"family": "wikisource", "code": "en"},
        "local_title": "Page:Canadian patent 29537.djvu/1",
    }
    refused = client.post("/links/", json=body)
    assert refused.status_code == 409
    assert "diverged" in refused.json()["detail"]

    forced = client.post("/links/", json={**body, "force": True})
    assert forced.status_code == 201
    assert forced.json()["origin"] == "manual"


def test_the_ladder_endpoint_reports_whether_the_anchor_is_current(
    client, engine
) -> None:
    with Session(engine) as session:
        local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
        local_page = _page(session, local, 1, body=_body(3, "A"), revid=5)
        remote_page = _page(session, remote, 1, body=_body(3, "B"), revid=900)
        assert_link(
            session,
            local_revision_pk=local_page.latest_revision_pk,
            remote_revision_pk=remote_page.latest_revision_pk,
            origin=LinkOrigin.copy,
        )
        session.commit()

    params = {
        "local_family": "mywikisource",
        "local_code": "en",
        "local_title": "Page:Canadian patent 29537.djvu/1",
        "remote_family": "wikisource",
        "remote_code": "en",
    }
    current = client.get("/links/", params=params).json()
    assert len(current["rungs"]) == 1
    assert current["anchor_is_current"] is True

    # The local side moves on: the link stays true, the anchor falls behind.
    with Session(engine) as session:
        # Both sites hold this title -- filter by site, or "the page" is two.
        local_site = session.exec(
            select(Site).where(Site.family == "mywikisource")
        ).one()
        page = session.exec(
            select(Page).where(
                Page.site_pk == local_site.pk, Page.title == params["local_title"]
            )
        ).one()
        record_head_revision(
            session,
            page,
            RemotePage(
                title=page.title,
                namespace_key=104,
                namespace_canonical="Page",
                content_model=PROOFREAD,
                text=_body(3, "A", "Now different."),
                revid=6,
                timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
        )
        session.commit()

    moved = client.get("/links/", params=params).json()
    assert len(moved["rungs"]) == 1
    assert moved["anchor_is_current"] is False
