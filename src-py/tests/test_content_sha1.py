import pytest
from conftest import CANADIAN_PATENT_INDEX
from wiki_harness import (
    DumpPage,
    PwbHarness,
    WikiApi,
    WikiStack,
    read_dump_text,
    scan_dump,
)

from wtbot.wiki.sha1 import content_sha1_base36

"""ProofreadPage hashes before and after its serialization transition.

``content.content_sha1`` and ``content.content_size`` are the values MediaWiki
computes over the bytes it stores.  Some historical ``proofread-page``
revisions predate the current serialization and their declared hashes no longer
match the text emitted by an export.  A ``Pywikibot touch edit`` reserialized
the page: that revision and every later revision must be self-consistent.

Regardless of history, every page's latest exported revision must have matching
text, SHA-1 and byte count.  Importing the dump into a fresh wiki must preserve
those properties.  The database and pywikibot checks below cover the imported
storage and the same API surface used by production.
"""

PAGE_2 = "Page:Canadian patent 29537.djvu/2"
DUMP = "Canadian_patent_29537_all.xml"

CONTENT_SQL = """
SELECT r.rev_id, r.rev_len, r.rev_sha1,
       c.content_size, c.content_sha1, c.content_address
FROM revision r
JOIN slots s   ON s.slot_revision_id = r.rev_id
JOIN content c ON c.content_id = s.slot_content_id
JOIN page p    ON p.page_id = r.rev_page
WHERE p.page_namespace = {ns} AND p.page_title = '{title}'
ORDER BY r.rev_timestamp, r.rev_id
"""


def _content_rows(
    wiki_pair: WikiStack, role: str, *, ns: int, title: str
) -> list[dict[str, str]]:
    return wiki_pair.sql(role, CONTENT_SQL.format(ns=ns, title=title))


@pytest.fixture(scope="module")
def imported_dump(
    wiki_pair: WikiStack, seeded_upstream: WikiApi
) -> dict[str, DumpPage]:
    """Re-export the imported fixture to observe portable text metadata."""
    return read_dump_text(wiki_pair.export_dump("upstream"))


@pytest.mark.slow
def test_rev_sha1_equals_the_main_slot_content_sha1(
    wiki_pair: WikiStack, seeded_upstream: WikiApi
) -> None:
    """``rev_sha1`` is not an independent quantity -- it is the main slot's
    ``content_sha1``, which is what T389026 ("drop rev_sha1, compute it from
    content_sha1") is acting on. Both are hashes of the *stored* bytes.
    """
    rows = _content_rows(
        wiki_pair, "upstream", ns=104, title="Canadian_patent_29537.djvu/2"
    )
    assert len(rows) == 4

    for row in rows:
        assert row["rev_sha1"] == row["content_sha1"], row
        assert row["rev_len"] == row["content_size"], row


def test_latest_dump_revision_is_self_consistent_for_every_page() -> None:
    """The current revision of every exported page is safe to identify by its
    declared SHA-1 and byte count, irrespective of inconsistent ancestors.
    """
    for page in scan_dump(DUMP).values():
        latest = page.latest
        assert latest.sha1_is_self_consistent, (page.title, latest)
        assert int(latest.bytes) == len(latest.text.encode()), (page.title, latest)


def test_touch_edit_and_every_later_dump_revision_are_self_consistent() -> None:
    """A touch edit is a known-good serialization boundary for that page."""
    touched_pages = 0
    for page in scan_dump(DUMP).values():
        touch_index = next(
            (
                index
                for index, revision in enumerate(page.revisions)
                if revision.comment == "Pywikibot touch edit"
            ),
            None,
        )
        if touch_index is None:
            continue

        touched_pages += 1
        for revision in page.revisions[touch_index:]:
            assert revision.sha1_is_self_consistent, (page.title, revision)
            assert int(revision.bytes) == len(revision.text.encode()), (
                page.title,
                revision,
            )

    assert touched_pages


@pytest.mark.slow
def test_latest_imported_revision_matches_dump_content_hash_and_size(
    imported_dump: dict[str, DumpPage],
) -> None:
    """A re-export preserves every page's known-good latest revision."""
    for page in scan_dump(DUMP).values():
        imported = imported_dump[page.title].latest
        expected = page.latest

        assert imported.text == expected.text, page.title
        assert imported.declared_sha1 == expected.declared_sha1, page.title
        assert imported.sha1_is_self_consistent, page.title
        assert int(imported.bytes) == len(imported.text.encode()), page.title


@pytest.mark.slow
def test_touch_edit_and_every_later_imported_revision_remain_self_consistent(
    imported_dump: dict[str, DumpPage],
) -> None:
    """The import retains the source's known-good touch boundary and suffix."""
    touched_pages = 0
    for page in scan_dump(DUMP).values():
        touch_index = next(
            (
                index
                for index, revision in enumerate(page.revisions)
                if revision.comment == "Pywikibot touch edit"
            ),
            None,
        )
        if touch_index is None:
            continue

        touched_pages += 1
        imported = imported_dump[page.title].revisions
        assert len(imported) == len(page.revisions), page.title

        for expected, actual in zip(
            page.revisions[touch_index:],
            imported[touch_index:],
            strict=True,
        ):
            assert actual.text == expected.text, (page.title, expected.revid)
            assert actual.declared_sha1 == expected.content_sha1, (
                page.title,
                expected.revid,
            )
            assert actual.sha1_is_self_consistent, (page.title, expected.revid)
            assert int(actual.bytes) == len(actual.text.encode()), (
                page.title,
                expected.revid,
            )

    assert touched_pages


@pytest.mark.slow
def test_plain_wikitext_stores_exactly_what_it_serves(
    wiki_pair: WikiStack, local_pwb: PwbHarness, local_promoter: WikiApi
) -> None:
    """Scoping: the split is a proofread-page property, not a MediaWiki one.

    For a wikitext page, hashing the served text reproduces ``content_sha1``,
    so the wiki's hash is usable there.
    """
    title = "Project:Wikitext serialization probe"
    text = "Plain wikitext with a {{template}} and a [[link]].\n"
    local_promoter.edit(title, text, summary="serialization probe")

    rows = _content_rows(wiki_pair, "local", ns=4, title="Wikitext_serialization_probe")
    assert rows
    row = rows[-1]

    served = local_pwb.main_slot_text(title)
    assert content_sha1_base36(served) == row["content_sha1"]
    assert int(row["content_size"]) == len(served.encode())


@pytest.mark.slow
def test_index_content_model_round_trips(
    wiki_pair: WikiStack, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
) -> None:
    """The latest proofread-index API serialization matches imported storage."""
    rows = _content_rows(
        wiki_pair, "upstream", ns=106, title="Canadian_patent_29537.djvu"
    )
    assert rows

    served = upstream_pwb.main_slot_text(CANADIAN_PATENT_INDEX)
    assert content_sha1_base36(served) == rows[-1]["content_sha1"]
