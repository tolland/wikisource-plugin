import pytest
from conftest import CANADIAN_PATENT_INDEX, CANADIAN_PATENT_SCAN
from wiki_harness import WikiApi, WikiApiError, WikiStack

"""Harness-level checks for the two-wiki sync fixture.

These assert the *fixture* is sound before anything is built on it, and they
pin two empirical claims the sync design in docs/upstream-sync-TODO.md rests on:

- importDump preserves per-revision sha1, so a work copied by import shares a
  revision lineage with its source and the base discovery of section 4.2 can
  intersect on the server-provided hash;
- `createonly` turns a parallel creation into an error instead of the silent
  overwrite the current push path performs (section 5.6).
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


def test_import_preserves_revision_history_and_sha1(
    seeded_upstream: WikiApi,
) -> None:
    """The dump for Page/2 carries four revisions whose quality level rises
    3 -> 4. Both the depth of history and the per-revision sha1 must survive,
    or rung 2 of the base ladder has nothing to intersect on.
    """
    revisions = seeded_upstream.revisions(PAGE_2, limit=50)
    assert len(revisions) >= 4

    sha1s = [rev.sha1 for rev in revisions]
    assert all(sha1s), "revisions imported without sha1"
    # Real content hashes from the en.wikisource dump; these are stable across
    # wikis precisely because sha1 is over the raw revision text.
    assert "ber7rim00nw9gknuje381xd89o14ne7" in sha1s
    assert "7qzy4bystlkoytnzaivpq46nv4bbd1d" in sha1s

    # Contributors come across too -- attribution is part of what an import
    # preserves and an API copy destroys.
    assert {rev.user for rev in revisions} & {"T. Mazzei", "Kathleen.wright5"}


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
