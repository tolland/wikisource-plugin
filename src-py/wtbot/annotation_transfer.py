import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from wtbot.annotation_store import (
    SqlAnnotationStore,
    SqlBoxLinkStore,
    SqlTextAnchorStore,
)
from wtbot.model.annotation.box_range_link import BoxRangeLink
from wtbot.model.annotation.scan_annotation import AnnotationCategory, ScanAnnotation
from wtbot.model.annotation.text_target_anchor import TextTargetAnchor
from wtbot.model.wiki.site import Site
from wtbot.model.wiki.title import Title
from wtbot.timeutil import utcnow

"""Portable dump/load of the annotation tables.

Everything else in the SQLite cache is re-derivable: pages, revisions and
blobs can be fetched again from the wiki (or a mirror), and losing the
local edit history costs nothing a re-fetch cannot restore. Annotations are
the exception — boxes drawn over a scan, the text ranges they target, and
the links between them exist *only* here. That asymmetry is what makes an
otherwise disposable database awkward to migrate; this module removes it by
making the annotation tables a file.

The dump is keyed on identity a new database can still resolve: the site's
``label`` and the page ``title``, not the page pk. Title pks are local to one
database and change the moment the cache is rebuilt, so they are carried
only as an informational echo of where a record came from. Within a page,
the client-generated ``annotation_id`` is the join key, exactly as it is in
the database: boxes, anchors and links reference each other by it and are
carried across unchanged.

Loading is conservative. Nothing is created implicitly: a dumped record
whose site or page is absent from the target database is reported and
skipped rather than conjuring a Site or a placeholder Title. Rows that are
already present are left alone unless ``replace`` is asked for, so a load
is safe to re-run and safe to point at a database that has moved on.
"""

DUMP_VERSION = 1


class BoxRecord(BaseModel):
    """One ScanAnnotation, in normalized full-page coordinates."""

    annotation_id: str
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)
    label: str | None = None
    category: AnnotationCategory | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> "BoxRecord":
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError("box must fit inside the normalized page")
        return self


class TextAnchorRecord(BaseModel):
    """One TextTargetAnchor. ``anchor_revid`` travels with it: an anchor is
    only trustworthy against the revision it was measured on, and dropping
    the revid would silently turn a stale anchor into a fresh-looking one."""

    annotation_id: str
    text_start: int = Field(ge=0)
    text_end: int = Field(ge=0)
    anchor_revid: int | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "TextAnchorRecord":
        if self.text_end < self.text_start:
            raise ValueError("need 0 <= text_start <= text_end")
        return self


class BoxLinkRecord(BaseModel):
    """One BoxRangeLink: this box's content is destined for that range."""

    box_annotation_id: str
    range_annotation_id: str


class PageAnnotations(BaseModel):
    """Every annotation record belonging to one page, under the identity a
    different database can resolve it by."""

    site_label: str | None
    site_family: str
    site_code: str
    title: str
    #: The page pk this was dumped from — provenance only, never used to
    #: re-attach on load.
    source_page_pk: int
    boxes: list[BoxRecord] = Field(default_factory=list)
    anchors: list[TextAnchorRecord] = Field(default_factory=list)
    links: list[BoxLinkRecord] = Field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.boxes) + len(self.anchors) + len(self.links)


class AnnotationDump(BaseModel):
    version: int = DUMP_VERSION
    created_at: datetime = Field(default_factory=utcnow)
    pages: list[PageAnnotations] = Field(default_factory=list)

    @property
    def record_count(self) -> int:
        return sum(page.record_count for page in self.pages)

    def write(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "AnnotationDump":
        """Parse a dump file, refusing a version this build does not know how
        to read rather than half-importing it."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not parseable as JSON: {exc}") from exc
        version = payload.get("version")
        if version != DUMP_VERSION:
            raise ValueError(
                f"{path}: dump version {version!r}, this build reads {DUMP_VERSION}"
            )
        return cls.model_validate(payload)


@dataclass
class LoadReport:
    """What a load did, in enough detail to tell "nothing to do" from
    "nothing matched" — the two outcomes that look alike from the counts."""

    boxes: int = 0
    anchors: int = 0
    links: int = 0
    replaced: int = 0
    skipped_existing: int = 0
    #: "label/title" for records whose page is absent from this database.
    missing_pages: list[str] = field(default_factory=list)
    #: Site labels in the dump that this database does not know.
    missing_sites: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return self.boxes + self.anchors + self.links


def dump_annotations(
    engine: Engine, *, site_label: str | None = None, title: str | None = None
) -> AnnotationDump:
    """Collect the annotation tables, joined against Site and Title so each
    record carries a resolvable (label, title) address.

    [site_label] limits the dump to one registered wiki, [title] to one page
    within it. Pages with no annotation records of any kind are left out.
    """
    with Session(engine) as session:
        query = select(Title, Site).join(Site, Site.pk == Title.site_pk)
        if site_label is not None:
            query = query.where(Site.label == site_label)
        if title is not None:
            query = query.where(Title.title == title)

        boxes = SqlAnnotationStore(session)
        anchors = SqlTextAnchorStore(session)
        links = SqlBoxLinkStore(session)

        pages: list[PageAnnotations] = []
        for page, site in session.exec(query.order_by(Title.pk)).all():
            assert page.pk is not None
            record = PageAnnotations(
                site_label=site.label,
                site_family=site.family,
                site_code=site.code,
                title=page.title,
                source_page_pk=page.pk,
                boxes=[
                    BoxRecord(
                        annotation_id=row.annotation_id,
                        x=row.normalized_x,
                        y=row.normalized_y,
                        width=row.normalized_width,
                        height=row.normalized_height,
                        label=row.label,
                        category=row.category,
                    )
                    for row in boxes.list_for_page(page.pk)
                ],
                anchors=[
                    TextAnchorRecord(
                        annotation_id=row.annotation_id,
                        text_start=row.text_start,
                        text_end=row.text_end,
                        anchor_revid=row.anchor_revid,
                    )
                    for row in anchors.list_for_page(page.pk)
                ],
                links=[
                    BoxLinkRecord(
                        box_annotation_id=row.box_annotation_id,
                        range_annotation_id=row.range_annotation_id,
                    )
                    for row in links.list_for_page(page.pk)
                ],
            )
            if record.record_count:
                pages.append(record)

    return AnnotationDump(pages=pages)


def _resolve_page(session: Session, label: str | None, title: str) -> Title | None:
    site = session.exec(select(Site).where(Site.label == label)).first()
    if site is None:
        return None
    return session.exec(
        select(Title).where(Title.site_pk == site.pk, Title.title == title)
    ).first()


def load_annotations(
    engine: Engine,
    dump: AnnotationDump,
    *,
    site_label: str | None = None,
    replace: bool = False,
    dry_run: bool = False,
) -> LoadReport:
    """Write [dump] back into the annotation tables of [engine]'s database.

    Records are re-attached by (site label, page title); the pks in the dump
    are ignored, which is the point — the target database will have assigned
    its own. [site_label] overrides every record's label, for loading a dump
    taken from one registered wiki into a differently-labelled one.

    Existing rows are kept unless [replace], so re-running is safe. A record
    whose site or page is missing is reported, never created.
    """
    report = LoadReport()
    known_missing_sites: set[str] = set()

    with Session(engine) as session:
        boxes = SqlAnnotationStore(session)
        anchors = SqlTextAnchorStore(session)
        links = SqlBoxLinkStore(session)

        for record in dump.pages:
            label = site_label or record.site_label
            page = _resolve_page(session, label, record.title)
            if page is None:
                site_exists = (
                    session.exec(select(Site).where(Site.label == label)).first()
                    is not None
                )
                if not site_exists:
                    if label not in known_missing_sites:
                        known_missing_sites.add(label or "")
                        report.missing_sites.append(label or "(unlabelled)")
                report.missing_pages.append(f"{label}/{record.title}")
                continue
            title_pk = page.pk
            assert title_pk is not None

            for box in record.boxes:
                existing = boxes.get(title_pk, box.annotation_id)
                if existing is not None and not replace:
                    report.skipped_existing += 1
                    continue
                if existing is not None:
                    report.replaced += 1
                if not dry_run:
                    boxes.upsert(
                        ScanAnnotation(
                            title_pk=title_pk,
                            annotation_id=box.annotation_id,
                            normalized_x=box.x,
                            normalized_y=box.y,
                            normalized_width=box.width,
                            normalized_height=box.height,
                            label=box.label,
                            category=box.category,
                        )
                    )
                report.boxes += 1

            for anchor in record.anchors:
                existing_anchor = anchors.get(title_pk, anchor.annotation_id)
                if existing_anchor is not None and not replace:
                    report.skipped_existing += 1
                    continue
                if existing_anchor is not None:
                    report.replaced += 1
                if not dry_run:
                    anchors.upsert(
                        TextTargetAnchor(
                            title_pk=title_pk,
                            annotation_id=anchor.annotation_id,
                            text_start=anchor.text_start,
                            text_end=anchor.text_end,
                            anchor_revid=anchor.anchor_revid,
                        )
                    )
                report.anchors += 1

            # Links last: a link is only meaningful while both endpoints
            # exist, so one whose box or range did not make it across is
            # reported rather than written as a dangling row.
            for link in record.links:
                endpoints_present = (
                    boxes.get(title_pk, link.box_annotation_id) is not None
                    and anchors.get(title_pk, link.range_annotation_id) is not None
                )
                if not endpoints_present and not dry_run:
                    report.warnings.append(
                        f"{label}/{record.title}: link "
                        f"{link.box_annotation_id}→{link.range_annotation_id} "
                        "has a missing endpoint, skipped"
                    )
                    continue
                existing_link = links.get(title_pk, link.box_annotation_id)
                if existing_link is not None and not replace:
                    report.skipped_existing += 1
                    continue
                if existing_link is not None:
                    report.replaced += 1
                if not dry_run:
                    links.upsert(
                        BoxRangeLink(
                            title_pk=title_pk,
                            box_annotation_id=link.box_annotation_id,
                            range_annotation_id=link.range_annotation_id,
                        )
                    )
                report.links += 1

    return report
