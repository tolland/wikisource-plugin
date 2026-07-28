import pytest
from conftest import CANADIAN_PATENT_INDEX
from wiki_harness import PwbHarness, WikiApi, WikiStack, scan_dump

from wtbot.wiki.sha1 import content_sha1_base36, normalize_sha1

"""What MediaWiki actually hashes, read from the database rather than inferred.

``content.content_sha1`` and ``content.content_size`` are the values MediaWiki
computes over the bytes it *stores*. No read API exposes those bytes: for
``proofread-page`` the API serialises the stored structure back into
``text/x-wiki``, re-adding the ``<noinclude><pagequality …/></noinclude>``
header and ``<noinclude></noinclude>`` footer. That reconstruction is why a hash
of the served text need not equal ``content_sha1``.

Since the harness owns the database, these tests settle it directly instead of
reasoning from the outside, and they do it through pywikibot -- the library the
production fetch path uses -- so the claims transfer to wtbot rather than to
``requests``.

The open question they answer: **does it matter how a page arrived?** An
``importDump`` page and an API-saved page take different routes into the
``content`` table, and only one of them round-trips through
``ProofreadPageContentHandler``.
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
ORDER BY r.rev_timestamp
"""


def _content_rows(
    wiki_pair: WikiStack, role: str, *, ns: int, title: str
) -> list[dict[str, str]]:
    return wiki_pair.sql(role, CONTENT_SQL.format(ns=ns, title=title))


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


def test_pywikibot_reports_the_stored_hash_not_the_served_one(
    wiki_pair: WikiStack, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
) -> None:
    """The production fetch path sees ``content_sha1``, in hex.

    So ``Page.sha1`` in our schema is a hash of bytes we never receive. Whether
    it happens to match a hash of the text we *do* receive is the subject of the
    next two tests.
    """
    rows = _content_rows(
        wiki_pair, "upstream", ns=104, title="Canadian_patent_29537.djvu/2"
    )
    stored = {row["content_sha1"] for row in rows}

    page = upstream_pwb.page(PAGE_2)
    reported = normalize_sha1(page.latest_revision.sha1)

    assert reported in stored
    assert reported == normalize_sha1(rows[-1]["content_sha1"])


def test_imported_pages_store_the_served_text_verbatim(
    wiki_pair: WikiStack, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
) -> None:
    """importDump writes the dump's text straight into ``content``.

    The stored bytes therefore *are* the served bytes, so hashing what we
    receive reproduces ``content_sha1`` exactly -- and the dump's own ``sha1``
    attribute (the source wiki's stored hash) does not match, because
    en.wikisource stored a different serialization.
    """
    rows = _content_rows(
        wiki_pair, "upstream", ns=104, title="Canadian_patent_29537.djvu/2"
    )
    dump_revisions = scan_dump(DUMP)[PAGE_2].revisions

    stored_hashes = {row["content_sha1"] for row in rows}
    assert stored_hashes == {rev.content_sha1 for rev in dump_revisions}

    # Sizes agree with the served text, not with what en.wikisource recorded.
    stored_sizes = {int(row["content_size"]) for row in rows}
    assert stored_sizes == {len(rev.text.encode()) for rev in dump_revisions}

    # And the source wiki's own hashes are absent -- three of the four differ.
    source_hashes = {rev.declared_sha1 for rev in dump_revisions}
    assert len(source_hashes - stored_hashes) == 3


def test_an_api_save_stores_a_different_serialization(
    wiki_pair: WikiStack, local_pwb: PwbHarness, local_promoter: WikiApi
) -> None:
    """The other route in: a normal edit round-trips through
    ``ProofreadPageContentHandler``, which stores the structure rather than the
    wikitext wrapper.

    The stored form drops the ``<noinclude>`` header and footer wrappers, so
    ``content_size`` is short by exactly their length and ``content_sha1``
    hashes something we never receive. This is the split that makes the wiki's
    own hash unusable as a cross-wiki identity token -- and it is not a legacy
    artefact: it happens on a wiki installed minutes ago.
    """
    title = "Page:Harness serialization probe.djvu/1"
    header = '<noinclude><pagequality level="1" user="Promoter" /></noinclude>'
    footer = "<noinclude></noinclude>"
    body = "Line one.\n\nLine two.\n"
    served_expected = f"{header}{body}{footer}"

    local_promoter.edit(title, served_expected, summary="serialization probe")

    rows = _content_rows(
        wiki_pair, "local", ns=104, title="Harness_serialization_probe.djvu/1"
    )
    assert rows, "probe page not found in the content table"
    row = rows[-1]

    served = local_pwb.main_slot_text(title)
    assert served == served_expected

    stored_size = int(row["content_size"])
    if stored_size == len(served.encode()):
        pytest.skip(
            "this wiki stored the wikitext form verbatim; no wrapper split to assert"
        )

    # Stored form omits both <noinclude> wrappers.
    assert stored_size == len(served.encode()) - len(header) - len(footer)
    assert row["content_sha1"] != content_sha1_base36(served)
    assert content_sha1_base36(body) == row["content_sha1"]


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


def test_index_content_model_round_trips(
    wiki_pair: WikiStack, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
) -> None:
    """proofread-index measured the same way, since section 4.2 claims it is
    unaffected."""
    rows = _content_rows(
        wiki_pair, "upstream", ns=106, title="Canadian_patent_29537.djvu"
    )
    assert rows

    served = upstream_pwb.main_slot_text(CANADIAN_PATENT_INDEX)
    assert content_sha1_base36(served) == rows[-1]["content_sha1"]
