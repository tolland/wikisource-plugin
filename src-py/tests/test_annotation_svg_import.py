from pathlib import Path

import pytest
from sqlmodel import Session

from wtbot.annotation_store import SqlAnnotationStore
from wtbot.annotation_svg_import import import_svg_annotations, parse_svg_rects
from wtbot.model import Page, ScanAnnotation, Site
from wtbot.model.namespace import NsRole

"""Tests for the one-shot import of legacy per-page SVG annotation
documents into the ScanAnnotation table."""

SVG = """<svg xmlns="http://www.w3.org/2000/svg"
            xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
            viewBox="0 0 1000 800" width="264.58mm" height="211.66mm">
  <image href="../page_images/scan.jpg" width="1000" height="800"/>
  <g id="annotations" transform="translate(5,5)">
    <rect id="r1" x="10" y="20" width="30" height="40" data-label="para 1"/>
    <rect id="r2" x="0" y="0" width="10" height="10"
          transform="translate(100,0)" inkscape:label="moved"/>
    <rect id="r3" x="1" y="1" width="2" height="2" transform="rotate(45)"/>
    <ellipse id="e1" cx="500" cy="400" rx="50" ry="25"/>
  </g>
</svg>"""


def test_parse_applies_nested_translates_and_reports_the_rest():
    parsed = parse_svg_rects(SVG)
    rects = {r.id: r for r in parsed.rects}
    assert set(rects) == {"r1", "r2", "r3"}
    assert (rects["r1"].x, rects["r1"].y) == (15.0, 25.0)  # group translate
    assert rects["r1"].label == "para 1"
    assert (rects["r2"].x, rects["r2"].y) == (105.0, 5.0)  # own + group
    assert rects["r2"].label == "moved"
    assert any("rotate" in w for w in parsed.warnings)
    assert any("e1" in w and "not a rect" in w for w in parsed.warnings)


def test_parse_rejects_garbage():
    with pytest.raises(ValueError, match="SVG"):
        parse_svg_rects("<svg unclosed")


def _seed_page(engine) -> int:
    with Session(engine) as s:
        site = Site(family="wikisource", code="en")
        s.add(site)
        s.flush()
        page = Page(
            site_pk=site.pk,
            title="Page:Tractatus.djvu/1",
            namespace_role=NsRole.page,
            content_model="proofread-page",
        )
        s.add(page)
        s.commit()
        return page.pk


def _write_svg(blob_root: Path, name: str, text: str = SVG) -> None:
    svg_dir = blob_root / "annotations"
    svg_dir.mkdir(parents=True, exist_ok=True)
    (svg_dir / name).write_text(text, encoding="utf-8")


def test_import_inserts_rects_and_is_idempotent(engine, tmp_path):
    page_pk = _seed_page(engine)
    _write_svg(tmp_path, f"{page_pk}.svg")

    report = import_svg_annotations(engine, tmp_path)
    assert sorted(report.imported) == [
        f"{page_pk}/r1",
        f"{page_pk}/r2",
        f"{page_pk}/r3",
    ]
    with Session(engine) as s:
        rows = {
            a.annotation_id: a for a in SqlAnnotationStore(s).list_for_page(page_pk)
        }
    assert rows["r1"].x == 15.0 and rows["r1"].label == "para 1"

    # Re-run: everything already there, nothing rewritten.
    again = import_svg_annotations(engine, tmp_path)
    assert again.imported == []
    assert sorted(again.skipped_existing) == sorted(report.imported)


def test_import_existing_rows_win(engine, tmp_path):
    page_pk = _seed_page(engine)
    _write_svg(tmp_path, f"{page_pk}.svg")
    with Session(engine) as s:
        SqlAnnotationStore(s).upsert(
            ScanAnnotation(
                page_pk=page_pk, annotation_id="r1", x=999, y=0, width=1, height=1
            )
        )

    import_svg_annotations(engine, tmp_path)
    with Session(engine) as s:
        assert SqlAnnotationStore(s).get(page_pk, "r1").x == 999


def test_import_dry_run_writes_nothing(engine, tmp_path):
    page_pk = _seed_page(engine)
    _write_svg(tmp_path, f"{page_pk}.svg")

    report = import_svg_annotations(engine, tmp_path, dry_run=True)
    assert len(report.imported) == 3
    with Session(engine) as s:
        assert SqlAnnotationStore(s).list_for_page(page_pk) == []


def test_import_skips_orphans_and_odd_files(engine, tmp_path):
    _seed_page(engine)
    _write_svg(tmp_path, "99999.svg")  # no such Page row
    _write_svg(tmp_path, "notes.svg")  # not a page_pk name

    report = import_svg_annotations(engine, tmp_path)
    assert report.imported == []
    assert report.skipped_pages == ["99999.svg"]
    assert any("notes.svg" in w for w in report.warnings)


def test_import_without_directory_is_a_noop(engine, tmp_path):
    report = import_svg_annotations(engine, tmp_path)
    assert report.imported == []
