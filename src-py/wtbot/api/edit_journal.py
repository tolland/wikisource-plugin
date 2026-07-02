from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.model import EditJournal

router = APIRouter(prefix="/edit-journal", tags=["edit-journal"])


@router.get("/", response_model=list[EditJournal])
def list_edit_journal(
    session: Session = Depends(get_session),
    page_pk: int | None = None,
    committed: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[EditJournal]:
    statement = (
        select(EditJournal).order_by(EditJournal.saved_at).offset(offset).limit(limit)
    )
    if page_pk is not None:
        statement = statement.where(EditJournal.page_pk == page_pk)
    if committed is not None:
        statement = statement.where(EditJournal.committed == committed)
    return list(session.exec(statement).all())


@router.get("/{edit_journal_pk}", response_model=EditJournal)
def get_edit_journal(
    edit_journal_pk: int, session: Session = Depends(get_session)
) -> EditJournal:
    edit = session.get(EditJournal, edit_journal_pk)
    if edit is None:
        raise HTTPException(status_code=404, detail="edit journal row not found")
    return edit
