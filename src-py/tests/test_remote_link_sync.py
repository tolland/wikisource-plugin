from collections.abc import Iterator

import pytest
from sqlmodel import Session, select
from wiki_harness import (
    SCRATCH_PAGE,
    PwbHarness,
    WikiApi,
    advance_upstream,
    create_scratch_pair,
    diverge_locally,
    reconcile_to_upstream,
    remove_scratch_pair,
)

from wtbot.content_model import Significance, parse_document
from wtbot.model import FetchRequest, LinkOrigin, Page, Revision, Site
from wtbot.remote_link_store import (
    assert_link,
    corresponding_page,
    current_anchor,
    find_link,
    ladder,
)
from wtbot.revision_store import head_content
from wtbot.worker import run_pending

"""RemoteLink against two real wikis.

`test_remote_link.py` proves the rules in isolation, on rows written by hand.
This module proves they hold over revisions that came out of MediaWiki through
the production fetch path -- pywikibot, the worker, the revision store -- which
is where the assumptions actually get tested: that a copied page really does
come back with different attribution, that a real revid is what lands in the
link, and that a page pair keeps one ladder no matter which side is called
local.

The pair starts *converged* -- both containers import the same dump from the
same compose anchor -- so every difference below is one a test made, in a line
you can see. Stand the same base up by hand with

    docker compose --profile pair up -d --wait

and apply the same deltas from `wiki_harness.scenarios`.
"""

pytestmark = pytest.mark.slow


def _register(session: Session, harness: PwbHarness) -> Site:
    """A Site row for a harness wiki, keyed as pywikibot keys it."""
    site = Site(
        family=f"harness-{harness.endpoint.role}",
        code="en",
        api_url=harness.endpoint.api_url,
        label=harness.endpoint.role,
    )
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def _fetch(session: Session, site: Site, harness: PwbHarness, title: str) -> Page:
    """Pull one title through the real worker into the revision store."""
    session.add(FetchRequest(site_pk=site.pk, title=title))
    session.commit()
    handled = run_pending(session, lambda _: harness.client)
    assert handled >= 1, f"the worker did not fetch {title}"

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).one()
    assert page.latest_revision_pk is not None, f"{title} fetched without a revision"
    return page


def _head(session: Session, page: Page) -> Revision:
    session.refresh(page)
    return session.get(Revision, page.latest_revision_pk)


@pytest.fixture
def copied(
    seeded_upstream: WikiApi, seeded_local: WikiApi, local_promoter: WikiApi
) -> Iterator[tuple[WikiApi, WikiApi]]:
    """A disposable page pair, the local side an API-level copy of upstream's.

    Deliberately **not** the seeded work. These tests edit their subject, and
    nothing tears the stack down any more, so editing an imported page would
    leave the pair diverged for the next run -- which is exactly the failure
    that made a second `pytest -m slow` go red. The seeded work stays
    read-only; mutation happens on a page these tests own and remove.

    Saved on the local side as `Promoter`, so the two hold the same
    transcription under a username that exists on one wiki only -- the
    cross-site norm, constructed rather than hoped for. Removal runs as the
    sysop accounts on both sides, before as well as after: a run that died
    mid-test must not hand the next one a page with a history it did not
    expect.
    """
    remove_scratch_pair(seeded_upstream, seeded_local)
    create_scratch_pair(seeded_upstream, local_promoter)
    yield seeded_upstream, seeded_local
    remove_scratch_pair(seeded_upstream, seeded_local)


@pytest.fixture
def linked(
    session: Session, copied, upstream_pwb: PwbHarness, local_pwb: PwbHarness
) -> tuple[Page, Page]:
    """Both sides fetched into wtbot and linked `origin=copy`.

    This is the `wtctl adopt` step of docs/todo/upstream-sync-TODO.md priority 2:
    the copy is a
    fact known at the moment it happens, so it is recorded rather than
    re-derived by title matching later.
    """
    upstream_site = _register(session, upstream_pwb)
    local_site = _register(session, local_pwb)
    upstream_page = _fetch(session, upstream_site, upstream_pwb, SCRATCH_PAGE)
    local_page = _fetch(session, local_site, local_pwb, SCRATCH_PAGE)

    assert_link(
        session,
        local_revision_pk=_head(session, local_page).pk,
        remote_revision_pk=_head(session, upstream_page).pk,
        origin=LinkOrigin.copy,
    )
    session.commit()
    return local_page, upstream_page


def test_a_copied_page_links_two_real_revisions(
    session: Session, linked: tuple[Page, Page]
) -> None:
    local_page, upstream_page = linked
    anchor = current_anchor(
        session, page_pk=local_page.pk, other_page_pk=upstream_page.pk
    )

    assert anchor is not None
    assert anchor.origin is LinkOrigin.copy
    # Real revids from two independent wikis: they are site-local counters and
    # have no reason to coincide, which is why the link stores our pks.
    linked_revids = {
        session.get(Revision, anchor.local_revision_pk).revid,
        session.get(Revision, anchor.remote_revision_pk).revid,
    }
    assert linked_revids == {
        _head(session, local_page).revid,
        _head(session, upstream_page).revid,
    }


def test_the_copy_is_the_same_transcription_under_different_attribution(
    session: Session, linked: tuple[Page, Page]
) -> None:
    """The case the whole design turns on. ProofreadPage rewrites
    ``pagequality user=`` to the saving account, so a faithful copy differs
    from its source in a field that is not part of the transcription -- and the
    content hashes differ accordingly. Correspondence has to survive that."""
    local_page, upstream_page = linked
    local = head_content(session, local_page)
    upstream = head_content(session, upstream_page)

    comparison = parse_document(local.text, local.content_model).compare(
        parse_document(upstream.text, upstream.content_model)
    )

    assert comparison.same_transcription
    assert comparison.significance in {
        Significance.identical,
        Significance.metadata_only,
    }


def test_one_page_pair_has_one_ladder_whichever_way_it_is_asked(
    session: Session, linked: tuple[Page, Page]
) -> None:
    """The reversal hazard, on real rows. `local` and `remote` record the
    direction an assertion was made from, not a hierarchy, so re-asserting the
    pair the other way round must not create a second correspondence."""
    local_page, upstream_page = linked
    local_head = _head(session, local_page)
    upstream_head = _head(session, upstream_page)

    already = assert_link(
        session,
        local_revision_pk=upstream_head.pk,
        remote_revision_pk=local_head.pk,
        origin=LinkOrigin.manual,
    )
    session.commit()

    assert already.origin is LinkOrigin.copy
    forward = ladder(session, page_pk=local_page.pk, other_page_pk=upstream_page.pk)
    backward = ladder(session, page_pk=upstream_page.pk, other_page_pk=local_page.pk)
    assert len(forward) == 1
    assert forward == backward
    assert (
        find_link(
            session,
            revision_pk=upstream_head.pk,
            other_revision_pk=local_head.pk,
        ).pk
        == forward[0].pk
    )


def test_page_correspondence_resolves_across_the_two_sites(
    session: Session, linked: tuple[Page, Page]
) -> None:
    local_page, upstream_page = linked

    assert (
        corresponding_page(
            session, page_pk=local_page.pk, other_site_pk=upstream_page.site_pk
        ).pk
        == upstream_page.pk
    )
    assert (
        corresponding_page(
            session, page_pk=upstream_page.pk, other_site_pk=local_page.site_pk
        ).pk
        == local_page.pk
    )


def test_a_local_edit_leaves_the_anchor_behind_the_head(
    session: Session,
    linked: tuple[Page, Page],
    seeded_local: WikiApi,
    local_pwb: PwbHarness,
) -> None:
    """Divergence is visible as an anchor that is no longer the head, not as a
    missing link. The link stays true -- those two revisions really were the
    same content -- and it is the distance from it that says work has happened
    since."""
    local_page, upstream_page = linked
    anchored_revid = _head(session, local_page).revid

    diverge_locally(seeded_local)
    _fetch(session, session.get(Site, local_page.site_pk), local_pwb, SCRATCH_PAGE)

    anchor = current_anchor(
        session, page_pk=local_page.pk, other_page_pk=upstream_page.pk
    )
    new_head = _head(session, local_page)

    assert new_head.revid != anchored_revid
    assert anchor.local_revision_pk != new_head.pk
    assert session.get(Revision, anchor.local_revision_pk).revid == anchored_revid

    local = head_content(session, local_page)
    upstream = head_content(session, upstream_page)
    comparison = parse_document(local.text, local.content_model).compare(
        parse_document(upstream.text, upstream.content_model)
    )
    assert comparison.significance is Significance.content


def test_reconciling_appends_a_rung_rather_than_editing_the_broken_one(
    session: Session,
    linked: tuple[Page, Page],
    seeded_upstream: WikiApi,
    seeded_local: WikiApi,
    local_pwb: PwbHarness,
    upstream_pwb: PwbHarness,
) -> None:
    """Forward re-anchoring, end to end. Remote history is append-only, so a
    broken anchor is superseded by a new one rather than repaired -- and the
    ladder keeps both, which is what makes "what did we believe, and when"
    answerable after the fact."""
    local_page, upstream_page = linked

    diverge_locally(seeded_local)
    _fetch(session, session.get(Site, local_page.site_pk), local_pwb, SCRATCH_PAGE)

    # A rung is one-to-one. Reconciliation therefore needs a new revision on
    # both sites; reusing the original upstream revision would branch the
    # ladder by giving that revision two local counterparts.
    advance_upstream(seeded_upstream)
    _fetch(
        session,
        session.get(Site, upstream_page.site_pk),
        upstream_pwb,
        SCRATCH_PAGE,
    )
    reconcile_to_upstream(seeded_upstream, seeded_local)
    _fetch(session, session.get(Site, local_page.site_pk), local_pwb, SCRATCH_PAGE)

    reconciled_head = _head(session, local_page)
    assert_link(
        session,
        local_revision_pk=reconciled_head.pk,
        remote_revision_pk=_head(session, upstream_page).pk,
        origin=LinkOrigin.reconciled,
    )
    session.commit()

    rungs = ladder(session, page_pk=local_page.pk, other_page_pk=upstream_page.pk)
    assert [rung.origin for rung in rungs] == [
        LinkOrigin.copy,
        LinkOrigin.reconciled,
    ]
    anchor = current_anchor(
        session, page_pk=local_page.pk, other_page_pk=upstream_page.pk
    )
    assert anchor.local_revision_pk == reconciled_head.pk
