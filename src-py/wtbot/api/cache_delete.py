"""Explicitly forget one cached address, including its sync correspondence."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, update
from sqlmodel import Session, col, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import (
    IndexLink,
    PageLink,
    PageTreeLink,
    Promotion,
    PromotionBatch,
    Revision,
    RevisionLink,
    Title,
)
from wtbot.site_delete import TableRows
from wtbot.site_store import require_site
from wtbot.title_delete import blockers, delete_titles
from wtbot.title_store import canonical_spelling

router = APIRouter(prefix="/cache", tags=["cache"], route_class=DebugLoggingRoute)


class CacheDeletePlan(BaseModel):
    site_label: str
    title: str
    dry_run: bool
    counts: list[TableRows]


@router.delete("/title", response_model=CacheDeletePlan)
def delete_cached_title(
    label: str,
    title: str,
    dry_run: bool = True,
    discard_local_edits: bool = False,
    session: Session = Depends(get_session),
) -> CacheDeletePlan:
    site = require_site(session, label)
    titles = session.exec(
        select(Title).where(
            Title.site_pk == site.pk,
            func.replace(Title.title, "_", " ") == canonical_spelling(title),
        )
    ).all()
    if not titles:
        raise HTTPException(404, f"{title} is not cached on {label}")
    pks = [row.pk for row in titles]
    if not discard_local_edits and any(row.dirty for row in titles):
        raise HTTPException(
            409,
            "uncommitted local edits would be lost; pass --discard-local-edits to remove them",
        )
    if reasons := blockers(session, pks, include_sync=False):
        raise HTTPException(409, "; ".join(reasons))

    pairs = list(
        session.exec(
            select(PageLink.pk).where(
                or_(
                    col(PageLink.local_page_pk).in_(pks),
                    col(PageLink.remote_page_pk).in_(pks),
                )
            )
        )
    )
    revisions = list(
        session.exec(select(Revision.pk).where(col(Revision.page_pk).in_(pks)))
    )
    rungs = list(
        session.exec(
            select(RevisionLink.pk).where(
                or_(
                    col(RevisionLink.page_link_pk).in_(pairs),
                    col(RevisionLink.local_revision_pk).in_(revisions),
                    col(RevisionLink.remote_revision_pk).in_(revisions),
                )
            )
        )
    )
    batches = list(
        session.exec(
            select(PromotionBatch.pk).where(
                or_(
                    col(PromotionBatch.source_page_pk).in_(pks),
                    col(PromotionBatch.target_title_pk).in_(pks),
                    col(PromotionBatch.anchor_link_pk).in_(rungs),
                )
            )
        )
    )
    predicates = [
        (Promotion, col(Promotion.batch_pk).in_(batches)),
        (PromotionBatch, col(PromotionBatch.pk).in_(batches)),
        (RevisionLink, col(RevisionLink.pk).in_(rungs)),
        (IndexLink, col(IndexLink.pk).in_(pairs)),
        (PageTreeLink, col(PageTreeLink.pk).in_(pairs)),
        (PageLink, col(PageLink.pk).in_(pairs)),
    ]
    counts = [
        TableRows(
            table=model.__tablename__,
            rows=len(session.exec(select(model).where(clause)).all()),
        )
        for model, clause in predicates
    ]
    counts += [
        TableRows(table="revision", rows=len(revisions)),
        TableRows(table="title", rows=len(titles)),
    ]
    plan = CacheDeletePlan(
        site_label=label,
        title=canonical_spelling(title),
        dry_run=dry_run,
        counts=[count for count in counts if count.rows],
    )
    if not dry_run:
        # Promotions form a chain. Clear its self-reference before deleting.
        session.execute(
            update(Promotion)
            .where(col(Promotion.batch_pk).in_(batches))
            .values(predecessor_promotion_pk=None)
        )
        for model, clause in predicates:
            session.execute(delete(model).where(clause))
        delete_titles(session, pks)
    return plan
