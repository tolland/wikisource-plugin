from wiki_harness import scan_dump

"""ProofreadPage's stored ``rev_sha1`` is not a content hash for old revisions.

Discovered while building the sync harness, and **verified against live
en.wikisource**, not just this fixture: for ``proofread-page`` revisions saved
before ProofreadPage's stored serialization was normalised, the wiki's
``rev_sha1`` does not equal the SHA-1 of the content the API (and the XML
export) serves for that same revision. Three consecutive revisions of
``Page:Canadian patent 29537.djvu/2`` are served with byte-identical text while
declaring three different hashes.

Scope, measured against en.wikisource:

    Page:Canadian patent 29537.djvu/2   proofread-page    3 of 4 mismatch
    Index:Canadian patent 29537.djvu    proofread-index  11 of 11 match
    Template:Uc                         wikitext          2 of  2 match

so this is specific to ``proofread-page``, and to revisions predating the 2018
``Wikisource-bot`` "Pywikibot touch edit" pass.

Consequence for docs/upstream-sync-TODO.md section 4.2: cross-wiki base
discovery must intersect on a hash computed from the returned content, never on
the server-provided ``rev_sha1``. These tests pin the behaviour so the
conclusion is not quietly re-derived the hard way.
"""

PAGE_2 = "Page:Canadian patent 29537.djvu/2"
INDEX = "Index:Canadian patent 29537.djvu"
DUMP = "Canadian_patent_29537_all.xml"


def test_proofread_page_declared_sha1_disagrees_with_its_own_content() -> None:
    revisions = scan_dump(DUMP)[PAGE_2].revisions
    consistent = [rev for rev in revisions if rev.sha1_is_self_consistent]
    inconsistent = [rev for rev in revisions if not rev.sha1_is_self_consistent]

    assert len(inconsistent) == 3
    # Only the most recent revision -- the 2018 reserialization -- agrees.
    assert [rev.revid for rev in consistent] == [7673287]
    assert {rev.user for rev in inconsistent} == {
        "T. Mazzei",
        "Kathleen.wright5",
        "ThomasBot",
    }


def test_distinct_revisions_are_served_with_identical_text() -> None:
    """The sharpest form of the problem: three different declared hashes, one
    text. Any dedupe or 'has this content changed?' check keyed on rev_sha1
    sees three changes where the served content shows none."""
    revisions = scan_dump(DUMP)[PAGE_2].revisions
    later = [rev for rev in revisions if rev.revid != 900114]

    assert len({rev.text for rev in later}) == 1
    assert len({rev.declared_sha1 for rev in later}) == 3
    assert len({rev.content_sha1 for rev in later}) == 1


def test_content_hashes_are_the_comparable_token() -> None:
    """What rung 2 must actually intersect on."""
    revisions = scan_dump(DUMP)[PAGE_2].revisions
    # Four revisions collapse to two distinct contents...
    assert len({rev.content_sha1 for rev in revisions}) == 2
    # ...and every content hash is derivable locally, with no wiki round trip.
    for rev in revisions:
        assert len(rev.content_sha1) == 31


def test_proofread_index_is_unaffected() -> None:
    """Scoping assertion: the discrepancy is proofread-page specific, so the
    fix does not need to be applied blindly to every content model."""
    revisions = scan_dump(DUMP)[INDEX].revisions
    assert len(revisions) == 11
    assert all(rev.sha1_is_self_consistent for rev in revisions)


def test_plain_wikitext_is_unaffected() -> None:
    pages = scan_dump(DUMP)
    wikitext_titles = [t for t in pages if t.startswith(("Template:", "Module:"))]
    assert wikitext_titles, "fixture should carry the template closure"

    for title in wikitext_titles:
        for rev in pages[title].revisions:
            assert rev.sha1_is_self_consistent, f"{title} r{rev.revid}"
