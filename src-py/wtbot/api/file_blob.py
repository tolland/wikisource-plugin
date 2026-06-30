from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import FileBlob

router = APIRouter(prefix="/file-blobs", tags=["file-blobs"])


@router.get("/", response_model=list[FileBlob])
def list_file_blobs(
    session: Session = Depends(get_session),
    page_pk: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[FileBlob]:
    statement = select(FileBlob).order_by(FileBlob.pk).offset(offset).limit(limit)
    if page_pk is not None:
        statement = statement.where(FileBlob.page_pk == page_pk)
    return list(session.exec(statement).all())


@router.get("/{file_blob_pk}", response_model=FileBlob)
def get_file_blob(
    file_blob_pk: int, session: Session = Depends(get_session)
) -> FileBlob:
    file_blob = session.get(FileBlob, file_blob_pk)
    if file_blob is None:
        raise HTTPException(status_code=404, detail="file blob not found")
    return file_blob
