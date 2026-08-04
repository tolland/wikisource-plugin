from wiki_harness import scan_dump

from wtbot.content_model import (
    ProofreadPageDocument,
    Significance,
    WikitextDocument,
    parse_document,
)

"""Content-model-aware comparison, exercised against real en.wikisource bodies.

``Page:Canadian patent 29537.djvu/2`` is a useful fixture because its four
revisions cover every case in one page:

    r900114   level 3, T. Mazzei          "to constrict cheaper"  (a typo)
    r1193309  level 4, Kathleen.wright5   "to construct cheaper"  (fixed)
    r2650547  level 4, Kathleen.wright5   identical text
    r7673287  level 4, Kathleen.wright5   identical text

so it gives a real level transition, a real prose change, and real pairs that
differ in nothing at all.
"""

DUMP = "Canadian_patent_29537_all.xml"
PAGE_2 = "Page:Canadian patent 29537.djvu/2"


def _revisions() -> dict[int, ProofreadPageDocument]:
    page = scan_dump(DUMP)[PAGE_2]
    return {rev.revid: ProofreadPageDocument.parse(rev.text) for rev in page.revisions}


def test_parses_a_real_body_into_its_parts() -> None:
    doc = _revisions()[1193309]

    assert doc.level == 4
    assert doc.user == "Kathleen.wright5"
    assert doc.header == ""  # the pagequality tag was the whole header
    assert doc.footer == "\n<references/>"
    assert doc.body.startswith("To all whom it may concern")
    # The tag itself is never part of the comparable text.
    assert "pagequality" not in doc.comparable_text


def test_identical_revisions_compare_identical() -> None:
    revisions = _revisions()
    result = revisions[2650547].compare(revisions[7673287])

    assert result.significance is Significance.identical
    assert result.text_equal
    assert result.differences == ()
    assert result.quality_delta == 0


def test_a_real_prose_change_is_a_content_difference() -> None:
    """r900114 -> r1193309 fixes 'constrict' to 'construct' *and* raises the
    level. The prose change is what dominates."""
    revisions = _revisions()
    result = revisions[900114].compare(revisions[1193309])

    assert result.significance is Significance.content
    assert not result.text_equal
    assert not result.same_transcription
    changed = {d.field for d in result.comparable_differences()}
    assert "body" in changed
    assert "level" in changed
    assert result.quality_delta == 1


def test_the_same_transcription_by_a_different_user_is_metadata_only() -> None:
    """The cross-site case. Two wikis holding the same transcription attribute
    it to whichever local account last set the level, so the bodies differ as
    bytes while the transcription is the same."""
    upstream = _revisions()[7673287]
    local = upstream.with_user("Tolland")

    assert local.serialize() != upstream.serialize()  # hashes would disagree

    result = upstream.compare(local)
    assert result.significance is Significance.metadata_only
    assert result.same_transcription
    assert [d.field for d in result.differences] == ["user"]
    # ...and that difference is explicitly not one that decides sameness.
    assert result.comparable_differences() == ()


def test_a_level_difference_alone_is_significant() -> None:
    """Equal words do not make it safe to overwrite: pushing a lower level over
    a higher one discards somebody's assessment."""
    proofread = _revisions()[7673287]
    not_proofread = ProofreadPageDocument(
        header=proofread.header,
        body=proofread.body,
        footer=proofread.footer,
        level=1,
        user=proofread.user,
    )

    result = proofread.compare(not_proofread)
    assert result.significance is Significance.metadata_significant
    assert result.same_transcription
    assert result.quality_delta == -3
    assert result.is_downgrade

    # And the other direction is an upgrade, not a downgrade.
    assert not not_proofread.compare(proofread).is_downgrade


def test_round_trips_every_revision_in_the_fixture() -> None:
    """Parsing must be lossless, or a promotion would rewrite bodies it was
    only meant to compare."""
    for page in scan_dump(DUMP).values():
        for revision in page.revisions:
            if not revision.text.startswith("<noinclude><pagequality"):
                continue
            assert ProofreadPageDocument.parse(revision.text).serialize() == (
                revision.text
            ), (page.title, revision.revid)


def test_a_body_without_wrappers_parses_as_all_body() -> None:
    """Forgiving rather than raising: a Page: written outside ProofreadPage
    should still be comparable."""
    doc = ProofreadPageDocument.parse("just some text\n")

    assert doc.body == "just some text\n"
    assert doc.level is None and doc.user is None
    assert doc.validation_errors() == ()


def test_a_level_without_a_user_is_invalid() -> None:
    """ProofreadPage always writes a user alongside a level, so a body missing
    one did not come from the extension and will not round-trip."""
    doc = ProofreadPageDocument.parse(
        '<noinclude><pagequality level="3" user="" /></noinclude>body<noinclude></noinclude>'
    )

    assert doc.level == 3
    assert doc.validation_errors() == ("pagequality level is set but user is empty",)


def test_a_running_header_is_compared_not_ignored() -> None:
    """The header holds more than the pagequality tag; dropping it wholesale
    would hide a real difference."""
    left = ProofreadPageDocument.parse(
        '<noinclude><pagequality level="3" user="A" />{{RunningHeader|left}}</noinclude>'
        "body<noinclude></noinclude>"
    )
    right = ProofreadPageDocument.parse(
        '<noinclude><pagequality level="3" user="A" />{{RunningHeader|right}}</noinclude>'
        "body<noinclude></noinclude>"
    )

    result = left.compare(right)
    assert result.significance is Significance.content
    assert [d.field for d in result.comparable_differences()] == ["header"]


def test_dispatch_picks_the_model() -> None:
    assert isinstance(parse_document("x", "proofread-page"), ProofreadPageDocument)
    assert isinstance(parse_document("x", "wikitext"), WikitextDocument)
    # Unknown models fall back to whole-text comparison rather than failing.
    assert isinstance(parse_document("x", "sanitized-css"), WikitextDocument)
    assert isinstance(parse_document("x", None), WikitextDocument)


def test_wikitext_compares_whole_text() -> None:
    assert (
        WikitextDocument.parse("a\r\nb")
        .compare(WikitextDocument.parse("a\nb"))
        .significance
        is Significance.identical
    ), "line endings are normalised"
    assert (
        WikitextDocument.parse("a ").compare(WikitextDocument.parse("a")).significance
        is Significance.content
    ), "trailing whitespace is not"
