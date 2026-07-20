from datetime import datetime
from typing import Protocol

from sqlmodel import Session, select

from wtbot.model.scan_annotation import ScanAnnotation
from wtbot.model.text_target_anchor import TextTargetAnchor

"""Storage seams for scan annotations and their text anchors.

The two halves of an annotation — the bounding box over the scan and the
anchor into the transcription text — are stored and edited independently,
joined by ``annotation_id``. Each half hides behind a Protocol so the
backing can be swapped later (a different database, a remote service, an
import/export format) without touching the API layer; the SQLModel-backed
implementations below are the defaults, wired up in wtbot.api.annotations.

The SQLModel row classes double as the value objects: an implementation
that doesn't persist through SQLModel still traffics in ``ScanAnnotation``
/ ``TextTargetAnchor`` instances (they are plain pydantic models unless
added to a Session).
"""


class AnnotationStore(Protocol):
    """Bounding boxes over a page's scan image, keyed (page_pk, annotation_id)."""

    def list_for_page(self, page_pk: int) -> list[ScanAnnotation]: ...

    def get(self, page_pk: int, annotation_id: str) -> ScanAnnotation | None: ...

    def upsert(self, annotation: ScanAnnotation) -> ScanAnnotation:
        """Insert, or update the row matching (page_pk, annotation_id).
        Geometry, label, and category are replaced wholesale."""
        ...

    def delete(self, page_pk: int, annotation_id: str) -> bool:
        """Remove the box; False if absent."""
        ...


class TextAnchorStore(Protocol):
    """Text-range anchors, keyed (page_pk, annotation_id) like the boxes."""

    def list_for_page(self, page_pk: int) -> list[TextTargetAnchor]: ...

    def get(self, page_pk: int, annotation_id: str) -> TextTargetAnchor | None: ...

    def upsert(self, anchor: TextTargetAnchor) -> TextTargetAnchor: ...

    def delete(self, page_pk: int, annotation_id: str) -> bool: ...


class SqlAnnotationStore:
    """AnnotationStore over the shared SQLite database."""

    def __init__(self, session: Session):
        self._session = session

    def list_for_page(self, page_pk: int) -> list[ScanAnnotation]:
        return list(
            self._session.exec(
                select(ScanAnnotation)
                .where(ScanAnnotation.page_pk == page_pk)
                .order_by(ScanAnnotation.pk)
            ).all()
        )

    def get(self, page_pk: int, annotation_id: str) -> ScanAnnotation | None:
        return self._session.exec(
            select(ScanAnnotation).where(
                ScanAnnotation.page_pk == page_pk,
                ScanAnnotation.annotation_id == annotation_id,
            )
        ).first()

    def upsert(self, annotation: ScanAnnotation) -> ScanAnnotation:
        row = self.get(annotation.page_pk, annotation.annotation_id)
        if row is None:
            row = annotation
        else:
            row.x = annotation.x
            row.y = annotation.y
            row.width = annotation.width
            row.height = annotation.height
            row.label = annotation.label
            row.category = annotation.category
            row.updated_at = datetime.now()
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def delete(self, page_pk: int, annotation_id: str) -> bool:
        row = self.get(page_pk, annotation_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True


class SqlTextAnchorStore:
    """TextAnchorStore over the shared SQLite database."""

    def __init__(self, session: Session):
        self._session = session

    def list_for_page(self, page_pk: int) -> list[TextTargetAnchor]:
        return list(
            self._session.exec(
                select(TextTargetAnchor)
                .where(TextTargetAnchor.page_pk == page_pk)
                .order_by(TextTargetAnchor.pk)
            ).all()
        )

    def get(self, page_pk: int, annotation_id: str) -> TextTargetAnchor | None:
        return self._session.exec(
            select(TextTargetAnchor).where(
                TextTargetAnchor.page_pk == page_pk,
                TextTargetAnchor.annotation_id == annotation_id,
            )
        ).first()

    def upsert(self, anchor: TextTargetAnchor) -> TextTargetAnchor:
        row = self.get(anchor.page_pk, anchor.annotation_id)
        if row is None:
            row = anchor
        else:
            row.text_start = anchor.text_start
            row.text_end = anchor.text_end
            row.anchor_revid = anchor.anchor_revid
            row.updated_at = datetime.now()
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def delete(self, page_pk: int, annotation_id: str) -> bool:
        row = self.get(page_pk, annotation_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True
