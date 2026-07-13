from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select

from wtbot.annotation_svg import SvgAnnotation, SvgAnnotationStore
from wtbot.api.page_image import _cache_path, _rendition_url
from wtbot.deps import get_session
from wtbot.model import Page
from wtbot.model.annotation_anchor import AnnotationAnchor
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore

"""Scan annotations for proofread pages — bounding boxes over the page
image, optionally anchored to a range of the transcription text.

Two faces over one store (see wtbot.annotation_svg for the split):

- typed, for the plugin: GET /pages/annotations lists boxes merged with
  their text anchors; PUT/DELETE /pages/annotations/{id} edit one box.
- raw, for everything else: GET/PUT /pages/annotations/svg move the whole
  SVG document, so the boxes can be edited in Inkscape/scripts and pushed
  back. Import reports anchors left dangling by out-of-band deletions.
"""

router = APIRouter(prefix="/pages", tags=["page-annotations"])


class AnnotationUpsert(BaseModel):
    x: float
    y: float
    width: float
    height: float
    label: str | None = None

    # Both set: linked (start == end inserts, < replaces). Both None: unlinked.
    text_start: int | None = None
    text_end: int | None = None
    anchor_revid: int | None = None

    # Scan raster size; required only for the first annotation of a page
    # (it becomes the new document's viewBox).
    image_width: float | None = None
    image_height: float | None = None

    @model_validator(mode="after")
    def _check_anchor(self) -> "AnnotationUpsert":
        if (self.text_start is None) != (self.text_end is None):
            raise ValueError("text_start and text_end must be set together")
        if self.text_start is not None:
            if self.text_start < 0 or self.text_end < self.text_start:
                raise ValueError("need 0 <= text_start <= text_end")
        if (self.image_width is None) != (self.image_height is None):
            raise ValueError("image_width and image_height must be set together")
        return self


class AnnotationOut(BaseModel):
    id: str
    shape: str
    x: float
    y: float
    width: float
    height: float
    label: str | None
    text_start: int | None
    text_end: int | None
    anchor_revid: int | None


class AnnotationList(BaseModel):
    annotations: list[AnnotationOut]
    # Anchors whose SVG element is gone (deleted out-of-band): kept, reported.
    dangling_anchor_ids: list[str]


def _page_for(session: Session, path: str) -> Page:
    node = resolve(PageStore(session), path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")
    return node.page


def _store(request: Request) -> SvgAnnotationStore:
    return SvgAnnotationStore(Path(request.app.state.blob_root))


def _anchors_by_id(session: Session, page_pk: int) -> dict[str, AnnotationAnchor]:
    rows = session.exec(
        select(AnnotationAnchor).where(AnnotationAnchor.page_pk == page_pk)
    ).all()
    return {row.annotation_id: row for row in rows}


def _merged(
    annotations: list[SvgAnnotation], anchors: dict[str, AnnotationAnchor]
) -> AnnotationList:
    outs = []
    for a in annotations:
        anchor = anchors.get(a.id)
        outs.append(
            AnnotationOut(
                id=a.id,
                shape=a.shape,
                x=a.x,
                y=a.y,
                width=a.width,
                height=a.height,
                label=a.label,
                text_start=anchor.text_start if anchor else None,
                text_end=anchor.text_end if anchor else None,
                anchor_revid=anchor.anchor_revid if anchor else None,
            )
        )
    present = {a.id for a in annotations}
    return AnnotationList(
        annotations=outs,
        dangling_anchor_ids=sorted(set(anchors) - present),
    )


# ---- raw SVG face (declared before /{annotation_id} so 'svg' isn't an id) ----


@router.get("/annotations/svg")
def get_annotations_svg(
    request: Request,
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
) -> Response:
    page = _page_for(session, path)
    document = _store(request).read_document(page.pk)
    if document is None:
        raise HTTPException(status_code=404, detail=f"no annotations yet for {path}")
    return Response(content=document, media_type="image/svg+xml")


@router.put("/annotations/svg")
async def put_annotations_svg(
    request: Request,
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> AnnotationList:
    page = _page_for(session, path)
    document = (await request.body()).decode("utf-8")
    try:
        annotations = _store(request).write_document(page.pk, document)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _merged(annotations, _anchors_by_id(session, page.pk))


# ---- typed face ---------------------------------------------------------------


@router.get("/annotations")
def list_annotations(
    request: Request,
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> AnnotationList:
    page = _page_for(session, path)
    return _merged(_store(request).read(page.pk), _anchors_by_id(session, page.pk))


@router.put("/annotations/{annotation_id}")
def upsert_annotation(
    annotation_id: str,
    body: AnnotationUpsert,
    request: Request,
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> AnnotationOut:
    page = _page_for(session, path)
    store = _store(request)

    image_size = None
    if body.image_width is not None and body.image_height is not None:
        image_size = (body.image_width, body.image_height)
    try:
        store.upsert_rect(
            page.pk,
            SvgAnnotation(
                id=annotation_id,
                shape="rect",
                x=body.x,
                y=body.y,
                width=body.width,
                height=body.height,
                label=body.label,
            ),
            image_size=image_size,
            image_href=_scan_href(session, page),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    anchor = session.exec(
        select(AnnotationAnchor).where(
            AnnotationAnchor.page_pk == page.pk,
            AnnotationAnchor.annotation_id == annotation_id,
        )
    ).first()
    if body.text_start is not None:
        if anchor is None:
            anchor = AnnotationAnchor(page_pk=page.pk, annotation_id=annotation_id)
        anchor.text_start = body.text_start
        anchor.text_end = body.text_end
        anchor.anchor_revid = body.anchor_revid
        anchor.updated_at = datetime.now()
        session.add(anchor)
    elif anchor is not None:  # unlink
        session.delete(anchor)
        anchor = None
    session.commit()

    return AnnotationOut(
        id=annotation_id,
        shape="rect",
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        label=body.label,
        text_start=anchor.text_start if anchor else None,
        text_end=anchor.text_end if anchor else None,
        anchor_revid=anchor.anchor_revid if anchor else None,
    )


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    annotation_id: str,
    request: Request,
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> None:
    page = _page_for(session, path)
    removed = _store(request).delete(page.pk, annotation_id)
    anchor = session.exec(
        select(AnnotationAnchor).where(
            AnnotationAnchor.page_pk == page.pk,
            AnnotationAnchor.annotation_id == annotation_id,
        )
    ).first()
    if anchor is not None:
        session.delete(anchor)
        session.commit()
    if not removed and anchor is None:
        raise HTTPException(status_code=404, detail=f"no annotation {annotation_id}")


def _scan_href(session: Session, page: Page) -> str | None:
    """Relative href from the annotation document to the cached scan raster
    (same naming as the /pages/image cache), so the SVG opened locally in
    Inkscape/a browser shows the boxes over the page. The raster file
    appears once the page image has been viewed; until then the link
    dangles harmlessly."""
    meta = PageStore(session).page_meta(page)
    url = _rendition_url(meta, None)
    if url is None:
        return None
    cache_name = _cache_path(Path("."), page.pk, None, url).name
    return f"../page_images/{cache_name}"
