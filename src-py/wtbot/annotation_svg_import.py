import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from wtbot.annotation_store import SqlAnnotationStore
from wtbot.model.page import Page
from wtbot.model.scan_annotation import ScanAnnotation

"""One-shot import of legacy per-page SVG annotation documents.

Before scan annotations moved into the ScanAnnotation table, each page's
boxes lived in ``blob_root/annotations/{page_pk}.svg``. This module walks
those files and inserts the rects it finds, so nothing drawn under the old
scheme is lost. It is deliberately conservative:

- only ``<rect>`` elements with an id are imported (the canvas only ever
  wrote rects; anything else was drawn out-of-band and is reported, not
  guessed at);
- ``translate(...)`` transforms on the rect or its ancestors are applied —
  the common leftover from Inkscape edits; any other transform function
  is reported and the element imported with only its translates applied;
- rows that already exist (same page_pk + annotation_id) are left alone,
  so re-running the import is safe.

The SVG files themselves are not touched; delete the ``annotations``
directory once you are happy with the result.
"""

_TRANSLATE = re.compile(
    r"translate\(\s*(-?[\d.eE+]+)\s*(?:[,\s]\s*(-?[\d.eE+]+))?\s*\)"
)
_TRANSFORM_FN = re.compile(r"([a-zA-Z]+)\s*\(")

LABEL_ATTR = "data-label"
INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


@dataclass(frozen=True, slots=True)
class ParsedRect:
    id: str
    x: float
    y: float
    width: float
    height: float
    label: str | None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    rects: list[ParsedRect]
    warnings: list[str]


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)  # "page_pk/annotation_id"
    skipped_existing: list[str] = field(default_factory=list)
    skipped_pages: list[str] = field(default_factory=list)  # files with no Page row
    warnings: list[str] = field(default_factory=list)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _translation_of(transform: str | None) -> tuple[float, float, list[str]]:
    """Sum of the translate() terms in [transform], plus any transform
    functions we do not handle (reported, not applied)."""
    if not transform:
        return 0.0, 0.0, []
    tx = ty = 0.0
    for m in _TRANSLATE.finditer(transform):
        tx += float(m.group(1))
        ty += float(m.group(2)) if m.group(2) is not None else 0.0
    unhandled = [
        fn for fn in _TRANSFORM_FN.findall(transform) if fn.lower() != "translate"
    ]
    return tx, ty, unhandled


def parse_svg_rects(text: str) -> ParsedDocument:
    """All identifiable <rect> elements in document order, with ancestor
    translate() transforms applied. Raises ValueError on unparseable SVG."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"not parseable as SVG: {exc}") from exc

    rects: list[ParsedRect] = []
    warnings: list[str] = []

    def walk(element: ET.Element, tx: float, ty: float) -> None:
        etx, ety, unhandled = _translation_of(element.get("transform"))
        tx, ty = tx + etx, ty + ety
        element_id = element.get("id")
        name = _local_name(element.tag)
        if name == "rect" and element_id:
            warnings.extend(
                f"transform '{fn}(...)' on {element_id} not applied" for fn in unhandled
            )
            try:
                rects.append(
                    ParsedRect(
                        id=element_id,
                        x=float(element.get("x", 0)) + tx,
                        y=float(element.get("y", 0)) + ty,
                        width=float(element.get("width", 0)),
                        height=float(element.get("height", 0)),
                        label=element.get(LABEL_ATTR) or element.get(INKSCAPE_LABEL),
                    )
                )
            except ValueError:
                warnings.append(f"{element_id}: non-numeric geometry, skipped")
        elif element_id and name not in ("svg", "g", "image"):
            # An identifiable non-rect shape (drawn in Inkscape): the old
            # store listed these read-only; the table has nowhere for them.
            warnings.append(
                f"{element_id}: <{name}> is not a rect, skipped — "
                "re-draw it as a box if it still matters"
            )
        for child in element:
            walk(child, tx, ty)

    walk(root, 0.0, 0.0)
    return ParsedDocument(rects=rects, warnings=warnings)


def import_svg_annotations(
    engine: Engine, blob_root: Path, dry_run: bool = False
) -> ImportReport:
    """Import every ``{page_pk}.svg`` under ``blob_root/annotations`` into
    the ScanAnnotation table. Existing rows win; SVG files are left in
    place either way."""
    report = ImportReport()
    svg_dir = Path(blob_root) / "annotations"
    if not svg_dir.is_dir():
        return report

    with Session(engine) as session:
        store = SqlAnnotationStore(session)
        for svg_path in sorted(svg_dir.glob("*.svg")):
            if not svg_path.stem.isdigit():
                report.warnings.append(f"{svg_path.name}: not a page_pk name, skipped")
                continue
            page_pk = int(svg_path.stem)
            if session.get(Page, page_pk) is None:
                report.skipped_pages.append(svg_path.name)
                continue
            try:
                parsed = parse_svg_rects(svg_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                report.warnings.append(f"{svg_path.name}: {exc}")
                continue
            report.warnings.extend(f"{svg_path.name}: {w}" for w in parsed.warnings)
            for rect in parsed.rects:
                if rect.width <= 0 or rect.height <= 0:
                    report.warnings.append(
                        f"{svg_path.name}: {rect.id}: empty geometry, skipped"
                    )
                    continue
                key = f"{page_pk}/{rect.id}"
                if store.get(page_pk, rect.id) is not None:
                    report.skipped_existing.append(key)
                    continue
                if not dry_run:
                    store.upsert(
                        ScanAnnotation(
                            page_pk=page_pk,
                            annotation_id=rect.id,
                            x=rect.x,
                            y=rect.y,
                            width=rect.width,
                            height=rect.height,
                            label=rect.label,
                        )
                    )
                report.imported.append(key)
    return report
