from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from wtbot.cli.commands.dev.dev import app
from wtbot.cli.commands.pdf_outline_utils import PageLabel, PdfOutline


def make_pdf(tmp_path: Path, *, toc=None, labels=None, count=20) -> Path:
    path = tmp_path / "outline.pdf"
    with pymupdf.open() as doc:
        for _ in range(count):
            doc.new_page()
        if toc:
            doc.set_toc(toc)
        if labels:
            doc.set_page_labels(labels)
        doc.save(path)
    return path


def test_no_toc_or_labels_uses_all_scans(tmp_path):
    outline = PdfOutline(make_pdf(tmp_path))
    assert len(outline.entries) == 1
    assert outline.entries[0].page_index == 0
    assert outline.entries[0].final_index == 19
    assert outline.pagelist(outline.entries[0]) == '<pagelist from="1" to="20" 1="1" />'
    assert outline.extract_outline() == outline.entries
    assert len(outline.entries) == 1


def test_no_toc_preserves_roman_and_decimal_transitions(tmp_path):
    outline = PdfOutline(
        make_pdf(
            tmp_path,
            labels=[
                {"startpage": 0, "prefix": "Cover", "style": ""},
                {"startpage": 3, "style": "r", "firstpagenum": 1},
                {"startpage": 12, "style": "D", "firstpagenum": 1},
            ],
        )
    )
    assert outline.pagelist(outline.entries[0]) == (
        '<pagelist from="1" to="20" 1to3="Cover" ' '4="1" 4to12="roman" 13="1" />'
    )


def test_bookmarks_include_first_scan_and_combine_duplicates(tmp_path):
    outline = PdfOutline(
        make_pdf(tmp_path, toc=[[1, "Cover", 1], [1, "Title", 1], [1, "Text", 5]])
    )
    assert [(e.pdf_page, e.final_index) for e in outline.entries] == [(1, 3), (5, 19)]
    assert outline.entries[0].title == "Cover / Title"


def test_missing_destinations_and_nested_bookmarks(tmp_path):
    outline = PdfOutline(make_pdf(tmp_path, toc=[[1, "Missing", -1], [2, "Nested", 2]]))
    assert len(outline.entries) == 1
    assert outline.entries[0].title == "Document"


def test_roman_section_uses_label_value_and_checks_actual_end(tmp_path):
    outline = PdfOutline(
        make_pdf(
            tmp_path,
            toc=[[1, "Contents", 8], [1, "Text", 14]],
            labels=[
                {"startpage": 0, "prefix": "Cover", "style": ""},
                {"startpage": 1, "style": "r", "firstpagenum": 1},
                {"startpage": 10, "style": "D", "firstpagenum": 1},
            ],
        )
    )
    assert outline.entries[0].pdf_page == 1
    contents = outline.entries[1]
    assert contents.page_label == "vii"
    assert outline.pagelist(contents) == (
        '<pagelist from="8" to="13" 8="7" 8to10="roman" 11="1" />'
    )


def test_uppercase_roman_reset_and_single_page_range(tmp_path):
    outline = PdfOutline(
        make_pdf(
            tmp_path,
            count=4,
            labels=[
                {"startpage": 0, "style": "R", "firstpagenum": 7},
                {"startpage": 3, "style": "R", "firstpagenum": 1},
            ],
        )
    )
    assert outline.pagelist(outline.entries[0]) == (
        '<pagelist from="1" to="4" 1="7" 1to3="highroman" 4="1" 4to4="highroman" />'
    )


def _parted_pdf(tmp_path) -> Path:
    return make_pdf(
        tmp_path,
        toc=[
            [1, "Part I", 5],
            [2, "Chapter 1", 9],
            [2, "Chapter 2", 13],
            [1, "Index", 17],
        ],
    )


def _sections(outline: PdfOutline) -> list[tuple[str, int, int, int]]:
    return [
        (entry.title, entry.level, entry.pdf_page, entry.final_index + 1)
        for entry in outline.entries
    ]


def test_depth_one_collapses_chapters_into_their_part(tmp_path):
    assert _sections(PdfOutline(_parted_pdf(tmp_path))) == [
        ("Pages before first bookmark", 1, 1, 4),
        ("Part I", 1, 5, 16),
        ("Index", 1, 17, 20),
    ]


def test_depth_two_splits_at_chapters_and_shortens_the_part(tmp_path):
    assert _sections(PdfOutline(_parted_pdf(tmp_path), depth=2)) == [
        ("Pages before first bookmark", 1, 1, 4),
        ("Part I", 1, 5, 8),
        ("Chapter 1", 2, 9, 12),
        ("Chapter 2", 2, 13, 16),
        ("Index", 1, 17, 20),
    ]


def test_part_sharing_a_scan_with_its_first_chapter_is_combined(tmp_path):
    outline = PdfOutline(
        make_pdf(tmp_path, toc=[[1, "Part I", 5], [2, "Chapter 1", 5]]), depth=2
    )
    assert [(e.title, e.level, e.pdf_page) for e in outline.entries] == [
        ("Pages before first bookmark", 1, 1),
        ("Part I / Chapter 1", 1, 5),
    ]


def test_depth_below_one_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="depth must be 1 or greater"):
        PdfOutline(make_pdf(tmp_path, count=1), depth=0)


def test_every_scan_is_accounted_for_exactly_once(tmp_path):
    outline = PdfOutline(_parted_pdf(tmp_path), depth=2)
    covered = [
        scan
        for entry in outline.entries
        for scan in range(entry.pdf_page, entry.final_index + 2)
    ]
    assert covered == list(range(1, outline.page_count + 1))


def test_verify_coverage_refuses_a_gap(tmp_path):
    outline = PdfOutline(make_pdf(tmp_path, count=4))
    first = outline.entries[0]
    outline.entries[0] = replace(first, final_index=1)
    with pytest.raises(ValueError, match="cover 2 of 4"):
        outline.verify_coverage()


def test_cli_depth_option_splits_at_chapters(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "extract-outline",
            "--pdf-filepath",
            str(_parted_pdf(tmp_path)),
            "--depth",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'Chapter 1\n<pagelist from="9" to="12"' in result.output


@pytest.mark.parametrize("label", ["civil", "IIII", "mixED", "A-ix", "", None])
def test_non_roman_labels(label):
    assert PageLabel.parse(label).number is None


def test_literal_label_is_escaped(tmp_path):
    outline = PdfOutline(
        make_pdf(
            tmp_path, count=1, labels=[{"startpage": 0, "prefix": 'A"&<', "style": ""}]
        )
    )
    assert '1to1="A&quot;&amp;&lt;"' in outline.pagelist(outline.entries[0])


def test_cli_outputs_plain_wikitext_without_debug_data(tmp_path):
    path = make_pdf(tmp_path, count=2)
    result = CliRunner().invoke(app, ["extract-outline", "--pdf-filepath", str(path)])
    assert result.exit_code == 0, result.output
    assert result.output == 'Document\n<pagelist from="1" to="2" 1="1" />\n\n'


def test_cli_invalid_pdf_has_actionable_error(tmp_path):
    path = tmp_path / "invalid.pdf"
    path.write_text("not a PDF")
    result = CliRunner().invoke(app, ["extract-outline", "--pdf-filepath", str(path)])
    assert result.exit_code == 2
    assert "Invalid value" in result.output
