from wtbot.locator_index import (
    NumeralStyle,
    compute_labels,
    from_roman,
    parse_pagelist_assignments,
    scan_section_occurrences,
    to_roman,
)

"""Unit tests for the pure locator-resolution module: roman numerals,
<pagelist> parsing/continuation, and <section>/{{anchor}} scanning.
See test_locator_index_api.py for the FastAPI layer over this."""


# ---------------------------------------------------------------------------
# Roman numerals
# ---------------------------------------------------------------------------


def test_to_roman_basic_values():
    assert to_roman(1) == "i"
    assert to_roman(4) == "iv"
    assert to_roman(9) == "ix"
    assert to_roman(14) == "xiv"
    assert to_roman(40) == "xl"
    assert to_roman(273) == "cclxxiii"


def test_to_roman_upper():
    assert to_roman(14, upper=True) == "XIV"


def test_to_roman_non_positive_falls_back_to_decimal():
    assert to_roman(0) == "0"
    assert to_roman(-3) == "-3"


def test_from_roman_round_trips_with_to_roman():
    for n in [1, 4, 9, 14, 40, 99, 273, 1994]:
        assert from_roman(to_roman(n)) == n


def test_from_roman_rejects_non_canonical_forms():
    assert from_roman("iiii") is None  # canonical is "iv"
    assert from_roman("vv") is None


def test_from_roman_rejects_ordinary_words():
    assert from_roman("adv") is None  # contains 'a'
    assert from_roman("half-title") is None
    assert from_roman("Cover") is None  # 'o' 'e' 'r' aren't roman digits


# ---------------------------------------------------------------------------
# <pagelist> parsing
# ---------------------------------------------------------------------------


def test_single_explicit_assignment():
    assignments = parse_pagelist_assignments("<pagelist from=82 to=94 82=48 />")
    assert assignments[82].kind == "numeral"
    assert assignments[82].style == NumeralStyle.arabic
    assert assignments[82].value == 48


def test_from_to_attributes_are_not_mistaken_for_page_assignments():
    # "from"/"to" don't start with a digit, so they should never be read as
    # page 0/whatever -- this is the whole reason no exclusion list is needed.
    assignments = parse_pagelist_assignments("<pagelist from=82 to=94 82=48 />")
    assert 0 not in assignments
    assert set(assignments) == {82}


def test_range_assignment_applies_to_every_page():
    assignments = parse_pagelist_assignments("<pagelist from=1 to=8 2to6=- />")
    for page in range(2, 7):
        assert assignments[page].kind == "blank"
    assert 1 not in assignments
    assert 7 not in assignments


def test_text_label_assignment():
    assignments = parse_pagelist_assignments("<pagelist from=1 to=8 7=half-title />")
    assert assignments[7].kind == "text"
    assert assignments[7].text == "half-title"


def test_roman_keyword_assignment():
    assignments = parse_pagelist_assignments("<pagelist from=11 to=30 11=roman />")
    assert assignments[11].kind == "numeral"
    assert assignments[11].style == NumeralStyle.roman
    assert assignments[11].value == 1


def test_multiple_pagelist_tags_all_contribute():
    body = (
        "Front Matter: <pagelist from=1 to=8 1=Cover 2to6=- 7=half-title 8=adv />\n"
        "Book 1 Chapter 1: <pagelist from=9 to=13 9=1 />\n"
    )
    assignments = parse_pagelist_assignments(body)
    assert assignments[1].text == "Cover"
    assert assignments[9].value == 1


def test_quoted_values_are_accepted_too():
    assignments = parse_pagelist_assignments('<pagelist from=1 to=8 1="Cover" 2="-" />')
    assert assignments[1].text == "Cover"
    assert assignments[2].kind == "blank"


# ---------------------------------------------------------------------------
# compute_labels — the continuation algorithm
# ---------------------------------------------------------------------------


def test_explicit_page_uses_its_own_value():
    assignments = parse_pagelist_assignments("<pagelist from=82 to=94 82=48 />")
    labels = compute_labels(assignments, [82])
    assert labels[82].label == "48"
    assert labels[82].confidence == "explicit"


def test_pages_after_an_anchor_count_on_arabically():
    assignments = parse_pagelist_assignments("<pagelist from=82 to=94 82=48 />")
    labels = compute_labels(assignments, [82, 83, 94])
    assert labels[83].label == "49"
    assert labels[83].confidence == "inferred"
    assert labels[94].label == "60"


def test_hertz_style_chapter_run_from_the_readme_example():
    # Book 1 Chapter 7: <pagelist from=155 to=170 155=121 170=- />
    # The "Index to definitions" example: scan page 163 is printed page 129.
    assignments = parse_pagelist_assignments(
        "<pagelist from=155 to=170 155=121 170=- />"
    )
    labels = compute_labels(assignments, list(range(155, 171)))
    assert labels[163].label == "129"
    assert labels[163].confidence == "inferred"
    assert labels[170].label is None  # explicit "-"
    assert labels[170].confidence == "explicit"


def test_blank_page_does_not_disturb_the_running_count():
    # 77=43, 78=- : pages 79-81 should still count on from 77, treating 78
    # as occupying a slot rather than being skipped over.
    assignments = parse_pagelist_assignments("<pagelist from=77 to=81 77=43 78=- />")
    labels = compute_labels(assignments, [79, 80, 81])
    assert [labels[p].label for p in (79, 80, 81)] == ["45", "46", "47"]


def test_text_label_page_does_not_disturb_the_running_count():
    assignments = parse_pagelist_assignments(
        "<pagelist from=1 to=10 1=5 3=frontispiece />"
    )
    labels = compute_labels(assignments, [1, 2, 3, 4])
    assert labels[2].label == "6"
    assert labels[4].label == "8"  # continues as if page 3 were numbered 7


def test_roman_style_continues_in_roman_after_the_switch():
    assignments = parse_pagelist_assignments("<pagelist from=11 to=15 11=roman />")
    labels = compute_labels(assignments, [11, 12, 13])
    assert labels[11].label == "i"
    assert labels[12].label == "ii"
    assert labels[13].label == "iii"
    assert labels[12].confidence == "inferred"


def test_page_before_any_anchor_is_unknown_not_guessed():
    assignments = parse_pagelist_assignments("<pagelist from=5 to=10 7=1 />")
    labels = compute_labels(assignments, [5, 6])
    assert labels[5].label is None
    assert labels[5].confidence == "unknown"


def test_a_new_numeric_anchor_overrides_the_previous_style():
    assignments = parse_pagelist_assignments("<pagelist from=1 to=20 1=roman 11=1 />")
    labels = compute_labels(assignments, [5, 15])
    assert labels[5].label == "v"
    assert labels[15].label == "5"  # back to arabic from page 11


# ---------------------------------------------------------------------------
# Real-world regressions found against Index:The principles of mechanics...
# ---------------------------------------------------------------------------


def test_a_range_key_is_clamped_to_its_own_tags_bounds():
    # Hertz's actual Index: a "Prefaces" pagelist (from=11 to=30) whose
    # "7to30=roman" key starts before that tag's own `from`. It must not
    # reach back into an unrelated earlier tag's pages 7/8.
    body = (
        "Front Matter: <pagelist from=1 to=8 1=Cover 2to6=- 7=half-title 8=adv />\n"
        "Prefaces: <pagelist from=11 to=30 11=5 7to30=roman />\n"
    )
    assignments = parse_pagelist_assignments(body)
    assert assignments[7].kind == "text"
    assert assignments[7].text == "half-title"
    assert assignments[8].kind == "text"
    assert assignments[8].text == "adv"


def test_a_single_key_below_its_tags_from_is_dropped():
    assignments = parse_pagelist_assignments("<pagelist from=10 to=20 5=48 />")
    assert 5 not in assignments


def test_a_single_key_above_its_tags_to_is_dropped():
    assignments = parse_pagelist_assignments("<pagelist from=10 to=20 25=48 />")
    assert 25 not in assignments


def test_a_range_key_is_dropped_entirely_when_wholly_outside_its_tags_bounds():
    assignments = parse_pagelist_assignments("<pagelist from=50 to=60 2to6=- />")
    assert not assignments


def test_roman_range_only_anchors_the_first_page():
    # Without this, "11to30=roman" would independently set every one of
    # 11..30 to "restart roman at i" instead of counting on from 11.
    assignments = parse_pagelist_assignments("<pagelist from=11 to=30 11to30=roman />")
    assert set(assignments) == {11}
    assert assignments[11].style == NumeralStyle.roman
    assert assignments[11].value == 1


def test_romans_advance_across_a_roman_range():
    assignments = parse_pagelist_assignments("<pagelist from=11 to=30 11to30=roman />")
    labels = compute_labels(assignments, [11, 12, 13])
    assert labels[11].label == "i"
    assert labels[12].label == "ii"
    assert labels[13].label == "iii"


def test_the_full_hertz_front_matter_and_prefaces_example_end_to_end():
    body = (
        "Front Matter: <pagelist from=1 to=8 1=Cover 2to6=- 7=half-title 8=adv />\n"
        "Prefaces: <pagelist from=11 to=30 11=5 7to30=roman />\n"
    )
    assignments = parse_pagelist_assignments(body)
    labels = compute_labels(assignments, list(range(1, 14)))
    assert [labels[p].label for p in range(1, 9)] == [
        "Cover", None, None, None, None, None, "half-title", "adv",
    ]  # fmt: skip
    assert labels[11].label == "i"
    assert labels[12].label == "ii"
    assert labels[13].label == "iii"


def test_a_highroman_range_also_only_anchors_the_first_page():
    assignments = parse_pagelist_assignments("<pagelist from=1 to=5 1to5=highroman />")
    labels = compute_labels(assignments, [1, 2, 3])
    assert labels[1].label == "I"
    assert labels[2].label == "II"
    assert labels[3].label == "III"


def test_a_range_of_a_bare_number_still_repeats_per_page():
    # Only the roman/highroman keyword gets the anchor-only treatment --
    # NtoM=<number> is a real (if unusual) "every page here reads N" case,
    # same as NtoM=- already is.
    assignments = parse_pagelist_assignments("<pagelist from=1 to=5 1to5=9 />")
    assert {p: a.value for p, a in assignments.items()} == {
        1: 9,
        2: 9,
        3: 9,
        4: 9,
        5: 9,
    }


def test_a_completely_bare_pagelist_defaults_to_one_to_one_numbering():
    # Index:NeglectedArgument.pdf: <pagelist /> with no attributes at all.
    assignments = parse_pagelist_assignments("<pagelist />")
    assert assignments == {}
    labels = compute_labels(assignments, [1, 2, 50])
    assert labels[1].label == "1"
    assert labels[2].label == "2"
    assert labels[50].label == "50"
    assert labels[1].confidence == "inferred"


def test_a_pagelist_tag_with_only_from_to_and_no_entries_also_defaults_to_one_to_one():
    assignments = parse_pagelist_assignments('<pagelist from="1" to="20" />')
    labels = compute_labels(assignments, [1, 20])
    assert labels[1].label == "1"
    assert labels[20].label == "20"


def test_no_pagelist_tag_at_all_also_defaults_to_one_to_one():
    assignments = parse_pagelist_assignments("just some prose, no <pagelist> here")
    labels = compute_labels(assignments, [1, 3])
    assert labels[1].label == "1"
    assert labels[3].label == "3"


def test_the_bare_default_does_not_apply_once_any_explicit_entry_exists():
    # A work with SOME pagelist data keeps the honest "unknown" for pages
    # before its first anchor -- only a wholly empty pagelist gets the
    # 1:1 default. (Same case as test_page_before_any_anchor_is_unknown_
    # not_guessed, restated here next to the bare-default tests it guards.)
    assignments = parse_pagelist_assignments("<pagelist from=5 to=10 7=1 />")
    labels = compute_labels(assignments, [5])
    assert labels[5].confidence == "unknown"


# ---------------------------------------------------------------------------
# Section/paragraph anchor scanning
# ---------------------------------------------------------------------------

_HERTZ_PARAGRAPH_273 = (
    "<section begin=\"p-273\" />{{anchor|p-273}}273. '''Definition'''. "
    "The instantaneous rate of change of the velocity of a system is called "
    "its acceleration."
    '<section end="p-273" />'
)


def test_scans_section_begin_and_end_and_anchor_template():
    occurrences = scan_section_occurrences(_HERTZ_PARAGRAPH_273, scan_page=163)
    roles = {(o.section_id, o.role) for o in occurrences}
    assert ("p-273", "begin") in roles
    assert ("p-273", "end") in roles
    assert ("p-273", "anchor_template") in roles
    assert all(o.scan_page == 163 for o in occurrences)


def test_single_quoted_section_tags_are_accepted():
    occurrences = scan_section_occurrences("<section begin='3.21' />", scan_page=5)
    assert occurrences == [
        type(occurrences[0])(section_id="3.21", scan_page=5, role="begin")
    ]


def test_no_section_tags_is_an_empty_list():
    assert (
        scan_section_occurrences("just plain wikitext, no markers", scan_page=1) == []
    )


def test_anchor_template_with_trailing_pipe_argument():
    occurrences = scan_section_occurrences("{{anchor|p-42|extra}}", scan_page=1)
    assert occurrences[0].section_id == "p-42"
