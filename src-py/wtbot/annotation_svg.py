import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from svgelements import SVG, Shape

"""Per-page SVG annotation documents.

One SVG per Page: leaf, at ``blob_root/annotations/{page_pk}.svg`` — the
source of truth for annotation *geometry*. The document is deliberately an
ordinary SVG: it links the cached scan raster with a relative href, so
opening it in Inkscape or a browser shows the boxes over the page, and any
SVG-aware tool can edit it out-of-band. Text anchors do NOT live here (see
wtbot.model.annotation_anchor); the element ``id`` is the join key.

Two access styles, matching the API's two faces:

- typed: read() extracts (id, bbox, label) from every identifiable shape,
  transform-aware via svgelements — a rect Inkscape wrapped in a
  translated <g> still reads back in scan-pixel coordinates. upsert_rect()
  / delete() do targeted ElementTree read-modify-write, preserving any
  foreign elements/attributes an external editor added.
- raw: read_document() / write_document() move the whole document verbatim
  (write validates it parses first).

Coordinates are scan pixels: the viewBox equals the full-resolution scan
size and the parse viewport is pinned to it, so physical-unit width/height
rewrites by external editors do not rescale anything.
"""

SVG_NS = "http://www.w3.org/2000/svg"

# Keep well-known prefixes stable when rewriting documents that came back
# from external editors.
for _prefix, _uri in {
    "": SVG_NS,
    "xlink": "http://www.w3.org/1999/xlink",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd",
}.items():
    ET.register_namespace(_prefix, _uri)

ANNOTATIONS_GROUP_ID = "annotations"
LABEL_ATTR = "data-label"


@dataclass(frozen=True, slots=True)
class SvgAnnotation:
    """One identifiable shape, reduced to its axis-aligned bounding box in
    scan-pixel coordinates. [shape] is the SVG element name ('rect',
    'ellipse', ...) — the canvas only draws/edits rects for now, but
    foreign shapes still list so nothing is invisible."""

    id: str
    shape: str
    x: float
    y: float
    width: float
    height: float
    label: str | None = None


class SvgAnnotationStore:
    def __init__(self, blob_root: Path):
        self._dir = Path(blob_root) / "annotations"

    def path_for(self, page_pk: int) -> Path:
        return self._dir / f"{page_pk}.svg"

    def exists(self, page_pk: int) -> bool:
        return self.path_for(page_pk).exists()

    # ---- raw face ---------------------------------------------------------

    def read_document(self, page_pk: int) -> str | None:
        path = self.path_for(page_pk)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write_document(self, page_pk: int, text: str) -> list[SvgAnnotation]:
        """Replace the whole document (the out-of-band editing round trip).
        Validates that it parses as SVG first; returns the annotations it
        contains. Raises ValueError on an unparseable document."""
        annotations = _parse_annotations(text)
        path = self.path_for(page_pk)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return annotations

    # ---- typed face -------------------------------------------------------

    def read(self, page_pk: int) -> list[SvgAnnotation]:
        text = self.read_document(page_pk)
        return _parse_annotations(text) if text is not None else []

    def upsert_rect(
        self,
        page_pk: int,
        annotation: SvgAnnotation,
        image_size: tuple[float, float] | None = None,
        image_href: str | None = None,
    ) -> None:
        """Write [annotation] as a <rect>, updating the element with its id
        in place (dropping any transform an external editor left — the new
        geometry is authoritative) or appending to the annotations group.

        A missing document is created as a skeleton, which needs
        [image_size] (scan width/height, the viewBox) — the caller's
        decoded image knows it; the store does not. [image_href] optionally
        links the scan raster into the skeleton. Raises ValueError when a
        skeleton is needed without a size, or the id belongs to a non-rect
        element."""
        path = self.path_for(page_pk)
        if path.exists():
            tree = ET.parse(path)
            root = tree.getroot()
        elif image_size is None:
            raise ValueError(
                f"no annotation document for page {page_pk} yet — "
                "image_size is required to create one"
            )
        else:
            root = _skeleton(image_size, image_href)
            tree = ET.ElementTree(root)

        element = _find_by_id(root, annotation.id)
        if element is None:
            element = ET.SubElement(_annotations_group(root), f"{{{SVG_NS}}}rect")
            element.set("id", annotation.id)
        elif _local_name(element.tag) != "rect":
            raise ValueError(
                f"annotation {annotation.id} is a {_local_name(element.tag)}, "
                "not a rect — edit it in an SVG editor instead"
            )
        element.set("x", _num(annotation.x))
        element.set("y", _num(annotation.y))
        element.set("width", _num(annotation.width))
        element.set("height", _num(annotation.height))
        element.attrib.pop("transform", None)
        if annotation.label is not None:
            element.set(LABEL_ATTR, annotation.label)
        else:
            element.attrib.pop(LABEL_ATTR, None)

        self._write_tree(tree, path)

    def delete(self, page_pk: int, annotation_id: str) -> bool:
        """Removes the element with [annotation_id]; False if absent."""
        path = self.path_for(page_pk)
        if not path.exists():
            return False
        tree = ET.parse(path)
        root = tree.getroot()
        for parent in root.iter():
            for child in list(parent):
                if child.get("id") == annotation_id:
                    parent.remove(child)
                    self._write_tree(tree, path)
                    return True
        return False

    def _write_tree(self, tree: ET.ElementTree, path: Path) -> None:
        ET.indent(tree)
        path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(path, encoding="unicode", xml_declaration=True)


def _skeleton(image_size: tuple[float, float], image_href: str | None) -> ET.Element:
    width, height = image_size
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "viewBox": f"0 0 {_num(width)} {_num(height)}",
            "width": _num(width),
            "height": _num(height),
        },
    )
    if image_href is not None:
        ET.SubElement(
            root,
            f"{{{SVG_NS}}}image",
            {"href": image_href, "width": _num(width), "height": _num(height)},
        )
    ET.SubElement(root, f"{{{SVG_NS}}}g", {"id": ANNOTATIONS_GROUP_ID})
    return root


def _parse_annotations(text: str) -> list[SvgAnnotation]:
    """All identifiable shapes in document order, transforms applied,
    reduced to bounding boxes in viewBox (scan pixel) coordinates."""
    viewport = _viewbox_size(text)
    try:
        svg = SVG.parse(
            StringIO(text),
            width=viewport[0] if viewport else None,
            height=viewport[1] if viewport else None,
        )
    except Exception as exc:  # svgelements raises assorted types
        raise ValueError(f"not parseable as SVG: {exc}") from exc

    annotations: list[SvgAnnotation] = []
    for element in svg.elements():
        element_id = getattr(element, "id", None)
        if not element_id or not isinstance(element, Shape):
            continue
        bbox = element.bbox()
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        values = dict(getattr(element, "values", {}) or {})
        annotations.append(
            SvgAnnotation(
                id=element_id,
                shape=values.get("tag", type(element).__name__.lower()),
                x=x0,
                y=y0,
                width=x1 - x0,
                height=y1 - y0,
                label=values.get(LABEL_ATTR) or values.get("inkscape:label"),
            )
        )
    return annotations


def _viewbox_size(text: str) -> tuple[float, float] | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"not parseable as SVG: {exc}") from exc
    viewbox = root.get("viewBox")
    if viewbox is None:
        return None
    parts = viewbox.replace(",", " ").split()
    if len(parts) != 4:
        return None
    return float(parts[2]), float(parts[3])


def _annotations_group(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if (
            _local_name(element.tag) == "g"
            and element.get("id") == ANNOTATIONS_GROUP_ID
        ):
            return element
    return ET.SubElement(root, f"{{{SVG_NS}}}g", {"id": ANNOTATIONS_GROUP_ID})


def _find_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    for element in root.iter():
        if element.get("id") == element_id and _local_name(element.tag) != "svg":
            return element
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _num(value: float) -> str:
    """Render 10.0 as '10' — SVG attributes stay human-readable."""
    return f"{value:g}"
