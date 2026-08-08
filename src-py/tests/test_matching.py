from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.content_model import Significance
from wtbot.matching import (
    MatchOutcome,
    compare_pages,
    confirm_proposals,
    propose_index_links,
)
from wtbot.model import (
    LinkOrigin,
    NsRole,
    Page,
    PageMeta,
    RemoteLink,
    Revision,
    Site,
)
from wtbot.remote_link_store import assert_link, current_anchor
from wtbot.revision_store import record_head_revision, record_history
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


def _site(session: Session, family: str, label: str | None = None) -> Site:
    site = Site(family=family, code="en", label=label or family)
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
    parentid: int | None = None,
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
                parentid=parentid,
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


def test_a_differing_quality_level_is_not_a_link(session: Session) -> None:
    """Same words, different proofreading state, and no anchor in the history
    held.

    Not proposable: the two revisions are *not* the same content, so a link
    would be false -- and it would overwrite the useful fact, which is that one
    side is an edit ahead of a base. Almost always the level bump is exactly
    that one edit, which is why the answer is to fetch more history rather than
    to link the heads.
    """
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(2, "LocalEditor"), revid=5)
    remote_page = _page(session, remote, 1, body=_body(4, "Hesperian"), revid=900)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.quality_differs
    assert not proposal.proposable


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
        "local_label": "mywikisource",
        "remote_label": "wikisource",
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
        "local_label": "mywikisource",
        "remote_label": "wikisource",
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
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "local_title": "Page:Canadian patent 29537.djvu/1",
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


def test_the_site_pair_is_inferred_from_a_naming_convention(client, engine) -> None:
    """The common setup needs no flags: labels matching a convention are paired
    without being named. `origin`/`upstream` is included because it already
    means exactly this to anyone who has forked a repository."""
    with Session(engine) as session:
        local = _site(session, "mywikisource", label="origin")
        remote = _site(session, "wikisource", label="upstream")
        _page(session, local, 1, body=_body(3, "LocalEditor"), revid=5)
        _page(session, remote, 1, body=_body(3, "Hesperian"), revid=900)

    response = client.post("/links/propose", json={"index_title": INDEX})

    assert response.status_code == 200
    assert response.json()["counts"] == {"same": 1}


def test_naming_only_one_side_is_refused(client, engine) -> None:
    """Pairing the named side with whatever else is registered would be one
    typo away from proposing links against the wrong wiki."""
    with Session(engine) as session:
        _site(session, "mywikisource", label="local")
        _site(session, "wikisource", label="remote")

    response = client.post(
        "/links/propose", json={"index_title": INDEX, "local_label": "local"}
    )

    assert response.status_code == 400
    assert "only the local site was named" in response.json()["detail"]


def test_unconventional_labels_ask_rather_than_guess(client, engine) -> None:
    """Two sites in no known convention have no inherent direction."""
    with Session(engine) as session:
        _site(session, "mywikisource", label="staging")
        _site(session, "wikisource", label="canonical")

    response = client.post("/links/propose", json={"index_title": INDEX})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "canonical, staging" in detail
    assert "origin/upstream" in detail


def _older(
    session: Session, page: Page, *, body: str, revid: int, parentid: int | None = None
) -> None:
    """An *older* revision, filled in behind the head.

    Which is the direction a history fetch works in: the head is what a normal
    fetch already recorded, and walking back adds ancestors without changing
    what "current" means.
    """
    record_history(
        session,
        page,
        [
            RemotePage(
                title=page.title,
                namespace_key=104,
                namespace_canonical="Page",
                content_model=PROOFREAD,
                text=body,
                revid=revid,
                parentid=parentid,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ],
    )
    session.commit()


def test_an_import_matching_an_older_upstream_revision_is_remote_ahead(
    session: Session,
) -> None:
    """The Hertz page 9 shape, and the common one.

    A local import matches upstream's *second-newest* revision; upstream then
    bumped the proofreading level. Comparing heads alone reports "same words,
    different level" and offers a link that would be false. The anchor is the
    pair that really is the same content, and the useful fact is the distance
    from it: upstream is one edit ahead.
    """
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 9, body=_body(1, "Admin"), revid=10779)
    remote_page = _page(
        session,
        remote,
        9,
        body=_body(3, "Tolland"),
        revid=15757208,
        parentid=15757193,
    )
    _older(session, remote_page, body=_body(1, "Tolland"), revid=15757193)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.remote_ahead
    assert proposal.proposable
    assert proposal.remote_ahead_by == 1
    assert proposal.local_ahead_by == 0
    assert not proposal.anchor_is_heads
    # The anchor is the older upstream revision, not its head.
    assert proposal.remote_revid == 15757193
    assert proposal.local_revid == 10779


def test_confirming_a_remote_ahead_pair_links_the_anchor_not_the_heads(
    session: Session,
) -> None:
    """The link has to name the base the unsynced revisions replay onto. Naming
    the heads would assert two revisions are the same content when they differ,
    and lose the base at the same time."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 9, body=_body(1, "Admin"), revid=10779)
    remote_page = _page(
        session,
        remote,
        9,
        body=_body(3, "Tolland"),
        revid=15757208,
        parentid=15757193,
    )
    _older(session, remote_page, body=_body(1, "Tolland"), revid=15757193)

    proposal = compare_pages(session, local_page, remote_page)
    (link,) = confirm_proposals(session, [proposal], origin=LinkOrigin.title_match)
    session.commit()

    anchored = session.get(Revision, link.remote_revision_pk)
    assert anchored.revid == 15757193
    assert anchored.revid != remote_page.revid


def test_local_edits_on_top_of_a_shared_base_are_local_ahead(
    session: Session,
) -> None:
    """The push direction: we proofread a page the other side has not seen."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(3, "Admin"), revid=11, parentid=10)
    remote_page = _page(session, remote, 1, body=_body(1, "Tolland"), revid=900)
    _older(session, local_page, body=_body(1, "Admin"), revid=10)

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.local_ahead
    assert proposal.local_ahead_by == 1
    assert proposal.proposable
    assert proposal.local_revid == 10


def test_the_newest_of_a_touch_edit_run_is_the_anchor(session: Session) -> None:
    """Several upstream revisions hold identical content, so several are
    equally true anchors. The newest is the tightest claim: an older one would
    report the touch edits as unsynced work when they carry no change."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(1, "Admin"), revid=10)
    remote_page = _page(
        session, remote, 1, body=_body(3, "Tolland"), revid=903, parentid=902
    )
    for revid, parent in ((902, 901), (901, 900), (900, None)):
        _older(
            session, remote_page, body=_body(1, "Tolland"), revid=revid, parentid=parent
        )

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.remote_ahead
    assert proposal.remote_revid == 902
    assert proposal.remote_ahead_by == 1


def test_an_incomplete_history_with_no_match_is_not_called_divergence(
    session: Session,
) -> None:
    """ "We did not look far enough" and "they disagree" need different actions,
    and only the first is fixed by fetching."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(1, "Admin", "Ours."), revid=10)
    # A head whose parent we do not hold: the history is known to be partial.
    remote_page = _page(
        session,
        remote,
        1,
        body=_body(1, "Tolland", "Theirs."),
        revid=950,
        parentid=949,
    )

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.history_exhausted
    assert not proposal.proposable
    assert "incomplete" in proposal.detail


def test_a_complete_history_with_no_match_is_divergence(session: Session) -> None:
    """Both sides held in full and nothing matches: that is a real conflict,
    and no amount of fetching changes it."""
    local, remote = _site(session, "mywikisource"), _site(session, "wikisource")
    local_page = _page(session, local, 1, body=_body(1, "Admin", "Ours."), revid=10)
    remote_page = _page(
        session, remote, 1, body=_body(1, "Tolland", "Theirs."), revid=900
    )

    proposal = compare_pages(session, local_page, remote_page)

    assert proposal.outcome is MatchOutcome.diverged
    assert not proposal.proposable
