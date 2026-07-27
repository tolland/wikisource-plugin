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


def test_seeded_upstream_has_the_work_and_its_scan(seeded_upstream: WikiApi) -> None:
    assert seeded_upstream.exists(CANADIAN_PATENT_INDEX)
    assert seeded_upstream.exists(CANADIAN_PATENT_SCAN)
    assert seeded_upstream.exists(PAGE_2)

    slots = seeded_upstream.list_index_pages(CANADIAN_PATENT_INDEX)
    assert slots, "ProofreadPage could not paginate the Index (DjVu support?)"


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


def test_createonly_rejects_a_parallel_creation(local_api: WikiApi) -> None:
    """The guard the current push path is missing: once the page exists,
    a create must fail rather than overwrite."""
    title = "Project:Parallel create probe"
    local_api.edit(title, "created by someone else", summary="first")

    with pytest.raises(WikiApiError) as excinfo:
        local_api.edit(title, "our body", createonly=True)
    assert excinfo.value.code == "articleexists"


def test_basetimestamp_rejects_an_intervening_edit(local_api: WikiApi) -> None:
    """Server-side conflict detection against the revision we actually based
    on -- not against whatever the client loaded moments ago."""
    title = "Project:Basetimestamp probe"
    local_api.edit(title, "original", summary="first")
    original = local_api.revisions(title, limit=1)[0]

    local_api.edit(title, "someone else's edit", summary="intervening")

    with pytest.raises(WikiApiError) as excinfo:
        local_api.edit(
            title,
            "our edit based on the original",
            basetimestamp=original.timestamp,
        )
    assert excinfo.value.code == "editconflict"
