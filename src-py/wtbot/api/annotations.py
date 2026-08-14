from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlmodel import Session

from wtbot.annotation_store import (
    AnnotationStore,
    BoxLinkStore,
    SqlAnnotationStore,
    SqlBoxLinkStore,
    SqlTextAnchorStore,
    TextAnchorStore,
)
from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import Page
from wtbot.model.annotation.box_range_link import BoxRangeLink
from wtbot.model.annotation.scan_annotation import AnnotationCategory, ScanAnnotation
from wtbot.model.annotation.text_target_anchor import TextTargetAnchor
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore

"""Scan annotations for proofread pages, in two independent surfaces joined
by the annotation id:

- /pages/annotations — bounding boxes over the page scan (geometry, label,
  category), edited from the image canvas. The category classifies the
  region for the OCR pipeline (header/footer/body/paragraph/section/ignore).
- /pages/text-anchors — ranges of the transcription text that are targets
  for OCR output or other processed text, edited from the text editor.
- /pages/box-links — explicit box→range links: a box's content is destined
  for the linked range. One link per box; several boxes may target one
  range.

Either side may exist without the other (draw the box first, or mark the
text first); deleting a box also drops its anchor, since the anchor's id
would otherwise point at nothing. Links only mean something while both
endpoints exist, so deleting a box drops its link and deleting a text
anchor drops every link targeting it.
"""

router = APIRouter(
    prefix="/pages", tags=["page-annotations"], route_class=DebugLoggingRoute
)


class AnnotationUpsert(BaseModel):
    x: float
    y: float
    width: float
    height: float
    label: str | None = None
    category: AnnotationCategory | None = None


class AnnotationOut(BaseModel):
    id: str
    x: float
    y: float
    width: float
    height: float
    label: str | None
    category: AnnotationCategory | None


class AnnotationList(BaseModel):
    annotations: list[AnnotationOut]


class TextAnchorUpsert(BaseModel):
    # text_start == text_end is an insertion point; < is a replace range.
    text_start: int
    text_end: int
    anchor_revid: int | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "TextAnchorUpsert":
        if self.text_start < 0 or self.text_end < self.text_start:
            raise ValueError("need 0 <= text_start <= text_end")
        return self


class TextAnchorOut(BaseModel):
    annotation_id: str
    text_start: int
    text_end: int
    anchor_revid: int | None


class TextAnchorList(BaseModel):
    anchors: list[TextAnchorOut]


class BoxLinkUpsert(BaseModel):
    range_annotation_id: str


class BoxLinkOut(BaseModel):
    box_annotation_id: str
    range_annotation_id: str


class BoxLinkList(BaseModel):
    links: list[BoxLinkOut]


def _page_for(session: Session, path: str) -> Page:
    node = resolve(PageStore(session), path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")
    return node.page


def get_annotation_store(
    session: Session = Depends(get_session),
) -> AnnotationStore:
    return SqlAnnotationStore(session)


def get_text_anchor_store(
    session: Session = Depends(get_session),
) -> TextAnchorStore:
    return SqlTextAnchorStore(session)


def get_box_link_store(
    session: Session = Depends(get_session),
) -> BoxLinkStore:
    return SqlBoxLinkStore(session)


def _annotation_out(row: ScanAnnotation) -> AnnotationOut:
    return AnnotationOut(
        id=row.annotation_id,
        x=row.x,
        y=row.y,
        width=row.width,
        height=row.height,
        label=row.label,
        category=row.category,
    )


def _link_out(row: BoxRangeLink) -> BoxLinkOut:
    return BoxLinkOut(
        box_annotation_id=row.box_annotation_id,
        range_annotation_id=row.range_annotation_id,
    )


def _anchor_out(row: TextTargetAnchor) -> TextAnchorOut:
    return TextAnchorOut(
        annotation_id=row.annotation_id,
        text_start=row.text_start,
        text_end=row.text_end,
        anchor_revid=row.anchor_revid,
    )


# ---- bounding boxes -----------------------------------------------------------


@router.get("/annotations")
def list_annotations(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
    store: AnnotationStore = Depends(get_annotation_store),
) -> AnnotationList:
    page = _page_for(session, path)
    return AnnotationList(
        annotations=[_annotation_out(row) for row in store.list_for_page(page.pk)]
    )


@router.put("/annotations/{annotation_id}")
def upsert_annotation(
    annotation_id: str,
    body: AnnotationUpsert,
    path: str = Query(...),
    session: Session = Depends(get_session),
    store: AnnotationStore = Depends(get_annotation_store),
) -> AnnotationOut:
    page = _page_for(session, path)
    row = store.upsert(
        ScanAnnotation(
            page_pk=page.pk,
            annotation_id=annotation_id,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            label=body.label,
            category=body.category,
        )
    )
    return _annotation_out(row)


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    annotation_id: str,
    path: str = Query(...),
    session: Session = Depends(get_session),
    store: AnnotationStore = Depends(get_annotation_store),
    anchors: TextAnchorStore = Depends(get_text_anchor_store),
    links: BoxLinkStore = Depends(get_box_link_store),
) -> None:
    page = _page_for(session, path)
    removed = store.delete(page.pk, annotation_id)
    anchor_removed = anchors.delete(page.pk, annotation_id)
    links.delete(page.pk, annotation_id)
    if anchor_removed:
        # The box's same-id anchor went with it, so links targeting that
        # anchor are dangling too.
        links.delete_for_range(page.pk, annotation_id)
    if not removed and not anchor_removed:
        raise HTTPException(status_code=404, detail=f"no annotation {annotation_id}")


# ---- text anchors -------------------------------------------------------------


@router.get("/text-anchors")
def list_text_anchors(
    path: str = Query(...),
    session: Session = Depends(get_session),
    anchors: TextAnchorStore = Depends(get_text_anchor_store),
) -> TextAnchorList:
    page = _page_for(session, path)
    return TextAnchorList(
        anchors=[_anchor_out(row) for row in anchors.list_for_page(page.pk)]
    )


@router.put("/text-anchors/{annotation_id}")
def upsert_text_anchor(
    annotation_id: str,
    body: TextAnchorUpsert,
    path: str = Query(...),
    session: Session = Depends(get_session),
    anchors: TextAnchorStore = Depends(get_text_anchor_store),
) -> TextAnchorOut:
    page = _page_for(session, path)
    row = anchors.upsert(
        TextTargetAnchor(
            page_pk=page.pk,
            annotation_id=annotation_id,
            text_start=body.text_start,
            text_end=body.text_end,
            anchor_revid=body.anchor_revid,
        )
    )
    return _anchor_out(row)


@router.delete("/text-anchors/{annotation_id}", status_code=204)
def delete_text_anchor(
    annotation_id: str,
    path: str = Query(...),
    session: Session = Depends(get_session),
    anchors: TextAnchorStore = Depends(get_text_anchor_store),
    links: BoxLinkStore = Depends(get_box_link_store),
) -> None:
    page = _page_for(session, path)
    if not anchors.delete(page.pk, annotation_id):
        raise HTTPException(status_code=404, detail=f"no text anchor {annotation_id}")
    # A link whose range is gone points at nothing — drop it with the range.
    links.delete_for_range(page.pk, annotation_id)


# ---- box→range links ----------------------------------------------------------


@router.get("/box-links")
def list_box_links(
    path: str = Query(...),
    session: Session = Depends(get_session),
    links: BoxLinkStore = Depends(get_box_link_store),
) -> BoxLinkList:
    page = _page_for(session, path)
    return BoxLinkList(links=[_link_out(row) for row in links.list_for_page(page.pk)])


@router.put("/box-links/{box_annotation_id}")
def upsert_box_link(
    box_annotation_id: str,
    body: BoxLinkUpsert,
    path: str = Query(...),
    session: Session = Depends(get_session),
    anchors: TextAnchorStore = Depends(get_text_anchor_store),
    links: BoxLinkStore = Depends(get_box_link_store),
) -> BoxLinkOut:
    page = _page_for(session, path)
    if anchors.get(page.pk, body.range_annotation_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"no text anchor {body.range_annotation_id} to link to",
        )
    row = links.upsert(
        BoxRangeLink(
            page_pk=page.pk,
            box_annotation_id=box_annotation_id,
            range_annotation_id=body.range_annotation_id,
        )
    )
    return _link_out(row)


@router.delete("/box-links/{box_annotation_id}", status_code=204)
def delete_box_link(
    box_annotation_id: str,
    path: str = Query(...),
    session: Session = Depends(get_session),
    links: BoxLinkStore = Depends(get_box_link_store),
) -> None:
    page = _page_for(session, path)
    if not links.delete(page.pk, box_annotation_id):
        raise HTTPException(status_code=404, detail=f"no box link {box_annotation_id}")
