from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from wtbot.api.schemas import (
    CommitRunResponse,
    PendingCommitJournal,
    PendingCommitPage,
)
from wtbot.commit_worker import run_pending_commit_for_page, run_pending_commits
from wtbot.deps import get_session
from wtbot.model import Commit, CommitStatus, EditJournal, Page

router = APIRouter(prefix="/commits", tags=["commits"])


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
        statement = statement.where(Commit.page_pk == page_pk)
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
        grouped.setdefault(row.page_pk, []).append(row)

    pending_pages: list[PendingCommitPage] = []
    for page_pk, journals in list(grouped.items())[offset : offset + limit]:
        page = session.get(Page, page_pk)
        if page is None:
            continue

        latest = journals[-1]
        base_revid = (
            latest.base_revid if latest.base_revid is not None else (page.revid or 0)
        )
        pending_pages.append(
            PendingCommitPage(
                page_pk=page_pk,
                site_pk=page.site_pk,
                title=page.title,
                current_revid=page.revid,
                base_revid=base_revid,
                comment=latest.comment,
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
    request: Request, session: Session = Depends(get_session)
) -> CommitRunResponse:
    factory = request.app.state.client_factory
    handled = 0
    exclude: set[int] = set()
    while True:
        n, failed = run_pending_commits(session, factory, limit=200, exclude=exclude)
        handled += n
        # Accumulate failed pages into exclude so the next batch doesn't retry
        # pages that already failed this sweep -- prevents the queue from cycling
        # on persistent conflicts/errors until the HTTP request times out.
        exclude |= failed
        if n == 0:
            break
    return CommitRunResponse(handled=handled)


@router.post("/{page_pk}", response_model=Commit)
def run_commit_for_page(
    page_pk: int, request: Request, session: Session = Depends(get_session)
) -> Commit:
    pending = session.exec(
        select(EditJournal.pk)
        .where(
            EditJournal.page_pk == page_pk,
            EditJournal.committed == False,  # noqa: E712
        )
        .limit(1)
    ).first()
    session.rollback()
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending edits for page")

    factory = request.app.state.client_factory
    run_pending_commit_for_page(session, page_pk, factory)
    commit = session.exec(
        select(Commit)
        .where(Commit.page_pk == page_pk)
        .order_by(Commit.created_at.desc(), Commit.pk.desc())
    ).first()
    if commit is None:
        raise HTTPException(status_code=500, detail="commit result was not recorded")
    return commit


@router.get("/{commit_pk}", response_model=Commit)
def get_commit(commit_pk: int, session: Session = Depends(get_session)) -> Commit:
    commit = session.get(Commit, commit_pk)
    if commit is None:
        raise HTTPException(status_code=404, detail="commit not found")
    return commit
