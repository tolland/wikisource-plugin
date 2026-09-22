from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from wtbot.annotation_store import (
    SqlAnnotationStore,
    SqlBoxLinkStore,
    SqlTextAnchorStore,
)
from wtbot.annotation_transfer import (
    AnnotationDump,
    dump_annotations,
    load_annotations,
)
from wtbot.db import create_db_engine, init_db
from wtbot.model import (
    AnnotationCategory,
    BoxRangeLink,
    NsRole,
    Page,
    ScanAnnotation,
    Site,
    TextTargetAnchor,
)

"""Round-tripping the annotation tables through a file.

The point of the exercise is the pk: annotations are the one thing in the
cache that cannot be re-fetched, and the database they are loaded back into
has renumbered every page. So the tests below deliberately load into a
*second* database whose page pks do not match the first.
"""

TITLE = "Page:Tractatus.djvu/1"


def _seed(engine: Engine, *, label: str = "local", pk_offset: int = 0) -> int:
    """A site + page, with [pk_offset] throwaway pages ahead of it so two
    databases seeded this way disagree about the real page's pk."""
    with Session(engine) as s:
        site = Site(family="wikisource", code="en", label=label)
        s.add(site)
        s.flush()
        for i in range(pk_offset):
            s.add(Page(site_pk=site.pk, title=f"Page:Filler/{i}"))
        s.flush()
        page = Page(
            site_pk=site.pk,
            title=TITLE,
            namespace_role=NsRole.page,
            content_model="proofread-page",
        )
        s.add(page)
        s.commit()
        return page.pk


def _seed_annotations(engine: Engine, page_pk: int) -> None:
    with Session(engine) as s:
        SqlAnnotationStore(s).upsert(
            ScanAnnotation(
                page_pk=page_pk,
                annotation_id="box-1",
                normalized_x=0.1,
                normalized_y=0.2,
                normalized_width=0.3,
                normalized_height=0.4,
                label="first paragraph",
                category=AnnotationCategory.paragraph,
            )
        )
        SqlTextAnchorStore(s).upsert(
            TextTargetAnchor(
                page_pk=page_pk,
                annotation_id="range-1",
                text_start=12,
                text_end=48,
                anchor_revid=907,
            )
        )
        SqlBoxLinkStore(s).upsert(
            BoxRangeLink(
                page_pk=page_pk,
                box_annotation_id="box-1",
                range_annotation_id="range-1",
            )
        )


@pytest.fixture
def other_engine(tmp_path: Path) -> Engine:
    """A second, independently numbered database to load dumps into."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'other.db'}")
    init_db(engine)
    return engine


def test_dump_carries_resolvable_identity_not_just_pks(engine):
    page_pk = _seed(engine)
    _seed_annotations(engine, page_pk)

    dump = dump_annotations(engine)

    assert len(dump.pages) == 1
    record = dump.pages[0]
    assert (record.site_label, record.title) == ("local", TITLE)
    assert record.source_page_pk == page_pk
    assert record.boxes[0].annotation_id == "box-1"
    assert record.boxes[0].category is AnnotationCategory.paragraph
    assert (record.anchors[0].text_start, record.anchors[0].anchor_revid) == (12, 907)
    assert record.links[0].box_annotation_id == "box-1"


def test_pages_without_annotations_are_left_out(engine):
    _seed(engine)

    assert dump_annotations(engine).pages == []


def test_round_trip_reattaches_against_a_different_page_pk(
    engine, other_engine, tmp_path
):
    source_pk = _seed(engine)
    _seed_annotations(engine, source_pk)
    target_pk = _seed(other_engine, pk_offset=3)
    assert target_pk != source_pk  # the whole reason the dump is title-keyed

    path = tmp_path / "annotations.json"
    dump_annotations(engine).write(path)
    report = load_annotations(other_engine, AnnotationDump.read(path))

    assert (report.boxes, report.anchors, report.links) == (1, 1, 1)
    assert report.missing_pages == []
    with Session(other_engine) as s:
        box = SqlAnnotationStore(s).get(target_pk, "box-1")
        assert box is not None
        assert (box.normalized_x, box.normalized_height) == (0.1, 0.4)
        assert box.category is AnnotationCategory.paragraph
        anchor = SqlTextAnchorStore(s).get(target_pk, "range-1")
        assert anchor is not None and anchor.anchor_revid == 907
        link = SqlBoxLinkStore(s).get(target_pk, "box-1")
        assert link is not None and link.range_annotation_id == "range-1"


def test_load_keeps_existing_rows_unless_replace_is_asked_for(engine, other_engine):
    source_pk = _seed(engine)
    _seed_annotations(engine, source_pk)
    target_pk = _seed(other_engine, pk_offset=2)
    with Session(other_engine) as s:
        SqlAnnotationStore(s).upsert(
            ScanAnnotation(
                page_pk=target_pk,
                annotation_id="box-1",
                normalized_x=0.9,
                normalized_y=0.9,
                normalized_width=0.05,
                normalized_height=0.05,
                label="drawn later",
            )
        )
    dump = dump_annotations(engine)

    report = load_annotations(other_engine, dump)
    assert report.skipped_existing == 1
    assert report.boxes == 0
    with Session(other_engine) as s:
        kept = SqlAnnotationStore(s).get(target_pk, "box-1")
        assert kept is not None and kept.label == "drawn later"

    # The anchor and link went in on the first pass, so the second pass
    # overwrites all three rows, not just the box that was held back.
    report = load_annotations(other_engine, dump, replace=True)
    assert (report.boxes, report.replaced) == (1, 3)
    with Session(other_engine) as s:
        replaced = SqlAnnotationStore(s).get(target_pk, "box-1")
        assert replaced is not None and replaced.label == "first paragraph"


def test_load_reports_rather_than_conjures_a_missing_page(engine, other_engine):
    source_pk = _seed(engine)
    _seed_annotations(engine, source_pk)
    _seed(other_engine, pk_offset=1)  # same site label, but not this page
    with Session(other_engine) as s:  # drop the page the dump refers to
        s.delete(s.exec(select(Page).where(Page.title == TITLE)).one())
        s.commit()

    report = load_annotations(other_engine, dump_annotations(engine))

    assert report.written == 0
    assert report.missing_pages == [f"local/{TITLE}"]
    assert report.missing_sites == []


def test_load_reports_an_unregistered_site(engine, other_engine):
    source_pk = _seed(engine)
    _seed_annotations(engine, source_pk)

    report = load_annotations(other_engine, dump_annotations(engine))

    assert report.missing_sites == ["local"]
    assert report.written == 0


def test_a_relabelled_site_can_be_loaded_with_an_override(engine, other_engine):
    source_pk = _seed(engine, label="staging")
    _seed_annotations(engine, source_pk)
    target_pk = _seed(other_engine, label="local", pk_offset=4)

    report = load_annotations(
        other_engine, dump_annotations(engine), site_label="local"
    )

    assert report.written == 3
    with Session(other_engine) as s:
        assert SqlAnnotationStore(s).get(target_pk, "box-1") is not None


def test_dump_can_be_narrowed_to_one_site_or_page(engine):
    page_pk = _seed(engine)
    _seed_annotations(engine, page_pk)

    assert dump_annotations(engine, site_label="elsewhere").pages == []
    assert dump_annotations(engine, title="Page:Other/1").pages == []
    assert len(dump_annotations(engine, site_label="local", title=TITLE).pages) == 1


def test_a_dump_from_a_future_version_is_refused(tmp_path):
    path = tmp_path / "future.json"
    path.write_text('{"version": 99, "pages": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="dump version"):
        AnnotationDump.read(path)


def test_a_link_with_a_missing_endpoint_is_reported_not_written(engine, other_engine):
    source_pk = _seed(engine)
    _seed_annotations(engine, source_pk)
    target_pk = _seed(other_engine, pk_offset=2)
    dump = dump_annotations(engine)
    dump.pages[0].anchors = []  # the range never made it across

    report = load_annotations(other_engine, dump)

    assert report.links == 0
    assert any("missing endpoint" in w for w in report.warnings)
    with Session(other_engine) as s:
        assert SqlBoxLinkStore(s).get(target_pk, "box-1") is None
