from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from wtbot.api.schemas import CommitRunResponse
from wtbot.commit_worker import run_pending_commits
from wtbot.deps import get_session
from wtbot.sqlmodel import Commit, CommitStatus

router = APIRouter(prefix="/commits", tags=["commits"])


@router.get("/", response_model=list[Commit])
def list_commits(
    session: Session = Depends(get_session),
    page_pk: int | None = None,
    status: CommitStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Commit]:
    statement = select(Commit).order_by(Commit.created_at).offset(offset).limit(limit)
    if page_pk is not None:
        statement = statement.where(Commit.page_pk == page_pk)
    if status is not None:
        statement = statement.where(Commit.status == status)
    return list(session.exec(statement).all())


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


@router.get("/{commit_pk}", response_model=Commit)
def get_commit(commit_pk: int, session: Session = Depends(get_session)) -> Commit:
    commit = session.get(Commit, commit_pk)
    if commit is None:
        raise HTTPException(status_code=404, detail="commit not found")
    return commit
