import time

import pytest
from conftest import CANADIAN_PATENT_INDEX, CANADIAN_PATENT_SCAN
from wiki_harness import WikiApi, WikiApiError, WikiStack, scan_dump

"""Harness-level checks for the two-wiki sync fixture.

These assert the *fixture* is sound before anything is built on it, and they
pin the empirical claims the sync design in docs/upstream-sync-TODO.md rests on:

- an import preserves revision depth and attribution, which an API-level copy
  would flatten;
- an importing wiki recomputes sha1 from the text it is given, so *content*
  hashes are the token comparable across wikis -- stored ``rev_sha1`` is not
  (see test_proofread_serialization for why);
- `createonly` and `basetimestamp` turn a parallel write into an error instead
  of the silent overwrite the current push path performs (section 5.6).
"""

PAGE_2 = "Page:Canadian patent 29537.djvu/2"


@pytest.mark.slow
def test_pair_starts_as_two_independent_wikis(
    wiki_pair: WikiStack, upstream_api: WikiApi, local_api: WikiApi
) -> None:
    assert wiki_pair.endpoint("upstream").base_url != (
        wiki_pair.endpoint("local").base_url
    )
    # A page created on one must not be visible on the other -- if the volumes
    # or ports were shared, every sync test would silently pass.
    upstream_api.edit("Project:Isolation probe", "upstream only")
    assert upstream_api.exists("Project:Isolation probe")
    assert not local_api.exists("Project:Isolation probe")


@pytest.mark.slow
def test_seeded_upstream_has_the_work_and_its_scan(seeded_upstream: WikiApi) -> None:
    assert seeded_upstream.exists(CANADIAN_PATENT_INDEX)
    assert seeded_upstream.exists(CANADIAN_PATENT_SCAN)
    assert seeded_upstream.exists(PAGE_2)

    slots = seeded_upstream.list_index_pages(CANADIAN_PATENT_INDEX)
    assert slots, "ProofreadPage could not paginate the Index (DjVu support?)"


@pytest.mark.slow
def test_the_pair_starts_converged(
    seeded_upstream: WikiApi, seeded_local: WikiApi
) -> None:
    """Both wikis seed themselves from the same compose anchor, so the pair
    begins as a mirror and any difference is one a test made.

    This is the invariant whose absence made "diverged" meaningless: only
    upstream was ever seeded, so the local side held a lone Page: with no
    Index:, no File:, and one revision.
    """
    for api, role in ((seeded_upstream, "upstream"), (seeded_local, "local")):
        assert api.exists(CANADIAN_PATENT_INDEX), role
        assert api.exists(CANADIAN_PATENT_SCAN), role
        assert api.list_index_pages(CANADIAN_PATENT_INDEX), role

    stale = (
        "the seeded work differs between the wikis. Nothing edits it -- mutating "
        "tests use SCRATCH_PAGE -- so this is either a stack dirtied by an older "
        "revision of these tests, or something edited it by hand. Reset with "
        "`PYTHONPATH=src-py/tests uv run python -m wiki_harness up --rebuild`."
    )
    assert seeded_upstream.page_text(PAGE_2) == seeded_local.page_text(PAGE_2), stale
    assert len(seeded_upstream.revisions(PAGE_2, limit=50)) == len(
        seeded_local.revisions(PAGE_2, limit=50)
    ), stale


@pytest.mark.slow
def test_the_two_wikis_do_not_agree_on_revision_ids(
    seeded_upstream: WikiApi, seeded_local: WikiApi
) -> None:
    """Same content, different revids -- on purpose.

    Two wikis installed from empty and seeded in the same order would otherwise
    assign the *same* revids to the same pages, and a bug that compared revids
    across sites would pass here while failing against real wikis. ``local``
    burns a few ids first (``SEED_REVID_BURN``) so that mistake fails loudly in
    the fixture instead.
    """
    upstream_revids = {rev.revid for rev in seeded_upstream.revisions(PAGE_2, limit=50)}
    local_revids = {rev.revid for rev in seeded_local.revisions(PAGE_2, limit=50)}

    assert upstream_revids
    assert not (upstream_revids & local_revids), (
        "the two wikis assigned overlapping revids; SEED_REVID_BURN did not take "
        "effect, and cross-site revid comparison would pass here undetected"
    )


@pytest.mark.slow
def test_import_preserves_revision_history(seeded_upstream: WikiApi) -> None:
    """Depth of history and attribution must survive the import -- an API-level
    copy would flatten both."""
    revisions = seeded_upstream.revisions(PAGE_2, limit=50)
    # Exactly four: more means a dump was imported twice, which silently
    # inflates every history-walk test built on this fixture.
    assert len(revisions) == 4
    assert all(rev.sha1 for rev in revisions), "revisions imported without sha1"
    assert {rev.user for rev in revisions} == {
        "imported>T. Mazzei",
        "imported>Kathleen.wright5",
        "imported>ThomasBot",
        "imported>Wikisource-bot",
    }


@pytest.mark.slow
def test_import_recomputes_sha1_from_content(seeded_upstream: WikiApi) -> None:
    """An importing wiki hashes the text it is given, so every imported
    revision's sha1 is the *content* hash -- not the ``rev_sha1`` the source
    wiki had frozen for it (see test_proofread_serialization).

    This is the invariant rung 2 of the base ladder has to build on: content
    hashes are comparable across wikis, stored rev_sha1 is not.
    """
    dump_page = scan_dump("Canadian_patent_29537_all.xml")[PAGE_2]
    expected = {rev.content_sha1 for rev in dump_page.revisions}

    revisions = seeded_upstream.revisions(PAGE_2, limit=50)
    assert {rev.sha1_base36 for rev in revisions} == expected

    # The latest revision is the one whose stored and content hashes agree on
    # the source wiki too, so it round-trips end to end.
    assert dump_page.latest.declared_sha1 == "ber7rim00nw9gknuje381xd89o14ne7"
    assert dump_page.latest.content_sha1 == dump_page.latest.declared_sha1
    assert dump_page.latest.declared_sha1 in {rev.sha1_base36 for rev in revisions}


@pytest.mark.slow
def test_createonly_rejects_a_parallel_creation(
    local_promoter: WikiApi, local_bystander: WikiApi
) -> None:
    """The guard the current push path is missing: once the page exists,
    a create must fail rather than overwrite."""
    title = "Project:Parallel create probe"
    local_bystander.edit(title, "created by someone else", summary="first")

    with pytest.raises(WikiApiError) as excinfo:
        local_promoter.edit(title, "our body", createonly=True)
    assert excinfo.value.code == "articleexists"


@pytest.mark.slow
def test_baserevid_rejects_an_intervening_edit(
    local_promoter: WikiApi, local_bystander: WikiApi
) -> None:
    """``baserevid`` is the conflict token to push with.

    It compares revision ids exactly, so unlike ``basetimestamp`` it is immune
    to the one-second timestamp resolution that
    test_basetimestamp_cannot_see_a_same_second_edit demonstrates.
    """
    title = "Project:Baserevid probe"
    local_promoter.edit(title, "original\ncontent\nhere\n", summary="first")
    original = local_promoter.revisions(title, limit=1)[0]

    local_bystander.edit(title, "totally different\nbystander text\n", summary="theirs")

    with pytest.raises(WikiApiError) as excinfo:
        local_promoter.edit(
            title,
            "our rewrite\nof everything\n",
            baserevid=original.revid,
        )
    assert excinfo.value.code == "editconflict"


@pytest.mark.slow
def test_basetimestamp_cannot_see_a_same_second_edit(
    local_promoter: WikiApi, local_bystander: WikiApi
) -> None:
    """``basetimestamp`` has one-second resolution, and silently misses an
    intervening edit made within the same second.

    ``EditPage`` (REL1_43, ~line 2310) detects a conflict via
    ``$this->edittime != $timestamp``, comparing MediaWiki timestamps, which are
    only accurate to the second. Two edits over localhost land well inside one
    second, so the guard sees nothing -- while ``baserevid`` catches it.

    This is why section 5.6 of docs/upstream-sync-TODO.md specifies
    ``baserevid``: a bot pushing quickly is exactly the workload that trips the
    resolution limit.
    """
    title = "Project:Basetimestamp resolution probe"
    local_promoter.edit(title, "original", summary="first")
    original = local_promoter.revisions(title, limit=1)[0]

    local_bystander.edit(title, "bystander edit", summary="theirs")
    intervening = local_bystander.revisions(title, limit=1)[0]

    if intervening.timestamp != original.timestamp:
        pytest.skip("edits landed in different seconds; resolution limit not exercised")

    # Same second: basetimestamp sees no change and the overwrite goes through.
    assert (
        local_promoter.edit(title, "ours", basetimestamp=original.timestamp).revid
        is not None
    )
    assert local_promoter.page_text(title) == "ours"

    # baserevid catches what basetimestamp missed.
    local_bystander.edit(title, "bystander again", summary="theirs again")
    stale = original.revid
    with pytest.raises(WikiApiError) as excinfo:
        local_promoter.edit(title, "ours again", baserevid=stale)
    assert excinfo.value.code == "editconflict"


@pytest.mark.slow
def test_basetimestamp_is_suppressed_against_your_own_edit(
    local_promoter: WikiApi,
) -> None:
    """MediaWiki deliberately suppresses edit conflicts with yourself.

    ``EditPage`` (REL1_43, ~line 2329) calls ``userWasLastToEdit`` and, when the
    requesting user made every intervening revision, sets ``isConflict = false``
    with the comment "Suppress edit conflict with self".

    The branch is guarded on ``$this->edittime``, and ApiEditPage only forwards
    ``wpEdittime`` when ``baserevid`` is unset -- so this suppression applies to
    the ``basetimestamp`` path only, and is a second reason to push with
    ``baserevid``.
    """
    title = "Project:Self-conflict probe"
    local_promoter.edit(title, "original", summary="first")
    original = local_promoter.revisions(title, limit=1)[0]

    # Wait out the one-second resolution so this test isolates the *self*
    # suppression rather than re-testing the timestamp granularity above.
    time.sleep(1.1)
    local_promoter.edit(title, "our own intervening edit", summary="intervening")

    result = local_promoter.edit(
        title,
        "our edit based on a now-stale revision",
        basetimestamp=original.timestamp,
    )
    assert result.revid is not None
    assert local_promoter.page_text(title) == "our edit based on a now-stale revision"
