import logging
from collections import Counter
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
)
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.schemas import (
    CommitPageRequest,
    CommitRunResponse,
    PendingCommitJournal,
    PendingCommitPage,
)
from wtbot.commit_worker import run_pending_commit_for_page, run_pending_commits
from wtbot.deps import get_session
from wtbot.fetch.fetch_worker import run_pending
from wtbot.model import (
    Commit,
    CommitStatus,
    EditJournal,
    FetchRequest,
    FetchStatus,
    Page,
    Title,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/commits", tags=["commits"], route_class=DebugLoggingRoute)


def _refetch_committed_pages(request: Request, request_pks: set[int]) -> None:
    """Read back only this commit run's queued pages, using a fresh session.

    Fetch failures remain visible on the queue; they cannot undo a remote save.
    The fetch worker stops on rate limits and leaves unprocessed rows pending.
    """
    log.info(
        "commit refetch started: %d queued request(s), ids=%s",
        len(request_pks),
        sorted(request_pks),
    )
    with Session(request.app.state.engine) as session:
        handled = run_pending(
            session,
            request.app.state.client_factory,
            request_pks=request_pks,
            limit=len(request_pks),
            blob_root=getattr(request.app.state, "blob_root", None),
        )
        statuses = Counter(
            session.exec(
                select(FetchRequest.status).where(FetchRequest.pk.in_(request_pks))
            ).all()
        )
        remaining = statuses[FetchStatus.pending] + statuses[FetchStatus.in_progress]
        errors = statuses[FetchStatus.error]
        report = log.warning if remaining or errors else log.info
        report(
            "commit refetch finished: handled=%d complete=%d errors=%d remaining=%d ids=%s",
            handled,
            statuses[FetchStatus.done],
            errors,
            remaining,
            sorted(request_pks),
        )


@router.get("/", response_model=list[Commit])
def list_commits(
    session: Session = Depends(get_session),
    page_pk: int | None = None,
    status: CommitStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Commit]:
    """

    :param session:
    :param page_pk:
    :param status:
    :param offset:
    :param limit:
    :return:
    """
    statement = select(Commit).order_by(Commit.created_at).offset(offset).limit(limit)
    if page_pk is not None:
        statement = statement.where(Commit.title_pk == page_pk)
    if status is not None:
        statement = statement.where(Commit.status == status)
    return list(session.exec(statement).all())


@router.get("/pending", response_model=list[PendingCommitPage])
def list_pending_commits(
    session: Session = Depends(get_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[PendingCommitPage]:
    rows = session.exec(
        select(EditJournal)
        .where(EditJournal.committed == False)  # noqa: E712
        .order_by(EditJournal.saved_at)
    ).all()

    grouped: dict[int, list[EditJournal]] = {}
    for row in rows:
        grouped.setdefault(row.title_pk, []).append(row)

    pending_pages: list[PendingCommitPage] = []
    for page_pk, journals in list(grouped.items())[offset : offset + limit]:
        title = session.get(Title, page_pk)
        if title is None:
            continue
        # None when the wiki does not hold the page: the push is a creation.
        page = session.get(Page, page_pk)
        revid = page.revid if page is not None else None

        latest = journals[-1]
        base_revid = (
            latest.base_revid if latest.base_revid is not None else (revid or 0)
        )
        pending_pages.append(
            PendingCommitPage(
                page_pk=page_pk,
                site_pk=title.site_pk,
                title=title.title,
                current_revid=revid,
                base_revid=base_revid,
                comment=latest.comment,
                base_body=page.text if page is not None else None,
                submitted_body=latest.body,
                pending_count=len(journals),
                first_saved_at=journals[0].saved_at.isoformat(),
                latest_saved_at=latest.saved_at.isoformat(),
                journals=[
                    PendingCommitJournal(
                        pk=row.pk or 0,
                        base_revid=row.base_revid,
                        body=row.body,
                        comment=row.comment,
                        saved_at=row.saved_at.isoformat(),
                    )
                    for row in journals
                ],
            )
        )
    return pending_pages


@router.post("/", response_model=CommitRunResponse)
def run_commits(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> CommitRunResponse:
    factory = request.app.state.client_factory
    refetch_pks: set[int] = set()
    handled = 0
    exclude: set[int] = set()
    while True:
        n, failed = run_pending_commits(
            session, factory, limit=200, exclude=exclude, refetch_pks=refetch_pks
        )
        handled += n
        # Accumulate failed pages into exclude so the next batch doesn't retry
        # pages that already failed this sweep -- prevents the queue from cycling
        # on persistent conflicts/errors until the HTTP request times out.
        exclude |= failed
        if n == 0:
            break
    if refetch_pks:
        background_tasks.add_task(_refetch_committed_pages, request, refetch_pks)
    return CommitRunResponse(handled=handled)


@router.post("/{page_pk}", response_model=Commit)
def run_commit_for_page(
    page_pk: int,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    body: Annotated[CommitPageRequest, Body()] = CommitPageRequest(),
    force: Annotated[
        bool,
        Query(
            description="When true, push the pending body without enforcing base_revid."
        ),
    ] = False,
) -> Commit:
    pending = session.exec(
        select(EditJournal.pk)
        .where(
            EditJournal.title_pk == page_pk,
            EditJournal.committed == False,  # noqa: E712
        )
        .limit(1)
    ).first()
    session.rollback()
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending edits for page")

    factory = request.app.state.client_factory
    refetch_pks: set[int] = set()
    run_pending_commit_for_page(
        session,
        page_pk,
        factory,
        force=force,
        comment=body.comment,
        refetch_pks=refetch_pks,
    )
    commit = session.exec(
        select(Commit)
        .where(Commit.title_pk == page_pk)
        .order_by(Commit.created_at.desc(), Commit.pk.desc())
    ).first()
    if commit is None:
        raise HTTPException(status_code=500, detail="commit result was not recorded")
    if refetch_pks:
        background_tasks.add_task(_refetch_committed_pages, request, refetch_pks)
    return commit


@router.delete("/{page_pk}/pending", response_model=CommitRunResponse)
def cancel_pending_commit_for_page(
    page_pk: int, session: Session = Depends(get_session)
) -> CommitRunResponse:
    rows = session.exec(
        select(EditJournal).where(
            EditJournal.title_pk == page_pk,
            EditJournal.committed == False,  # noqa: E712
        )
    ).all()
    if not rows:
        return CommitRunResponse(handled=0)

    try:
        for row in rows:
            session.delete(row)

        # The journal is keyed to the title, and so is dirty: a title with no
        # page behind it can hold saves too.
        title = session.get(Title, page_pk)
        if title is not None:
            title.dirty = False
            session.add(title)

        session.commit()
    except Exception:
        session.rollback()
        raise
    return CommitRunResponse(handled=len(rows))


@router.get("/{commit_pk}", response_model=Commit)
def get_commit(commit_pk: int, session: Session = Depends(get_session)) -> Commit:
    commit = session.get(Commit, commit_pk)
    if commit is None:
        raise HTTPException(status_code=404, detail="commit not found")
    return commit
