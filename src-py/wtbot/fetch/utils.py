from sqlalchemy import update
from sqlmodel import Session, select

from wtbot.db_session import read_snapshot, write_batch
from wtbot.model import (
    FetchRequest,
    FetchStatus,
    Site,
)
from wtbot.page_processors import (
    ClaimedFetchRequest,
)
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient
from wtbot.wiki.namespaces import sync_namespaces


def _claim_batch(session: Session, limit: int = 50) -> list[ClaimedFetchRequest]:
    """Claim up to 50 current-page reads for the next site's priority tier.

    The conditional UPDATE prevents two drainers claiming the same row.
    Snapshots leave the transaction before any network work begins.
    """
    if limit <= 0:
        return []
    order = (FetchRequest.priority.desc(), FetchRequest.requested_at, FetchRequest.pk)
    with read_snapshot(session):
        first = session.exec(
            select(FetchRequest)
            .where(FetchRequest.status == FetchStatus.pending)
            .order_by(*order)
            .limit(1)
        ).first()
        if first is None:
            return []
        candidates = list(
            session.exec(
                select(FetchRequest.pk)
                .where(
                    FetchRequest.status == FetchStatus.pending,
                    FetchRequest.site_pk == first.site_pk,
                    FetchRequest.priority == first.priority,
                )
                .order_by(*order)
                .limit(min(limit, 50))
            ).all()
        )
    with write_batch(session):
        rows = session.scalars(
            update(FetchRequest)
            .where(
                FetchRequest.pk.in_(candidates),
                FetchRequest.status == FetchStatus.pending,
            )
            .values(status=FetchStatus.in_progress, updated_at=utcnow())
            .returning(FetchRequest)
        ).all()
        snapshots = {row.pk: _snapshot_request(row) for row in rows}
        return [snapshots[pk] for pk in candidates if pk in snapshots]


def _maybe_sync_namespaces(session: Session, site: Site, client: WikiClient) -> None:
    """Sync siteinfo namespaces on first use of a site (no-op on subsequent calls)."""
    from wtbot.model import Namespace

    with read_snapshot(session):
        already = session.exec(
            select(Namespace).where(Namespace.site_pk == site.pk)
        ).first()
    if already is not None:
        return
    ns_dict = client.get_namespaces()
    if ns_dict is None:
        return
    sync_namespaces(session, site, ns_dict)
    session.rollback()


def _snapshot_request(req: FetchRequest) -> ClaimedFetchRequest:
    if req.pk is None:
        raise RuntimeError("cannot process an unpersisted fetch request")
    return ClaimedFetchRequest(
        pk=req.pk,
        site_pk=req.site_pk,
        parent_pk=req.parent_pk,
        title=req.title,
        kind=req.kind,
        depth=req.depth,
        revisions=req.revisions,
    )
