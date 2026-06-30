"""Sync-back endpoint (surface C).

The plugin POSTs here to push pending local edits (EditJournal rows) to the
wiki. Drains the queue inline, same shape as fetch.py's create_fetch -- a
background worker can replace the inline loop later without changing the
contract.
"""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from wtbot.api.schemas import CommitRunResponse
from wtbot.commit_worker import run_pending_commits
from wtbot.deps import get_session

router = APIRouter(prefix="/commit", tags=["commit"])


@router.post("/", response_model=CommitRunResponse)
def run_commits(
    request: Request, session: Session = Depends(get_session)
) -> CommitRunResponse:
    factory = request.app.state.client_factory
    handled = 0
    while True:
        n = run_pending_commits(session, factory, limit=200)
        handled += n
        if n == 0:
            break
    return CommitRunResponse(handled=handled)
