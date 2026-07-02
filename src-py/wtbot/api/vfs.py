from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from wtbot.api.debug_loggig_route import DebugLoggingRoute
from wtbot.api.schemas import (
    ChangesSinceResponse,
    CreateChildRequest,
    DeleteRequest,
    ListChildrenResponse,
    OperationResult,
    OperationStatus,
    ReadContentResponse,
    RenameRequest,
    Stat,
    StatBulkRequest,
    StatBulkResponse,
    WriteContentRequest,
    WriteResult,
)
from wtbot.deps import get_session
from wtbot.vfs import WikisourceVfs
from wtbot.vfs.errors import (
    BlobsNotImplemented,
    NotADirectory,
    NotAFile,
    NotFound,
    VfsError,
)

"""VFS endpoints — thin HTTP adapter over `wtbot.vfs`.

Path scheme (all relative to wikisource://):

  /                                       root — all sites
  /{family}/{code}/                       site root — Index pages for that site
  /{family}/{code}/{Index title}/         index dir — Pages + File subdir
  /{family}/{code}/{Index title}/wikitext            Index: description/pagelist wikitext
  /{family}/{code}/{Index title}/Pages/{Page title}  page wikitext file
  /{family}/{code}/{Index title}/{File title}/       file dir
  /{family}/{code}/{Index title}/{File title}/wikitext   File: description wikitext
  /{family}/{code}/{Index title}/{File title}/blob       binary (stub — 501)

All tree/classification logic lives in `wtbot.vfs`; this module only parses
params, delegates, and maps domain errors to HTTP status codes.

Write / rename / delete and the change feed are stubbed for now.
"""

router = APIRouter(prefix="/vfs", tags=["vfs"], route_class=DebugLoggingRoute)

_ERROR_STATUS: dict[type[VfsError], int] = {
    NotFound: 404,
    NotADirectory: 404,
    NotAFile: 400,
    BlobsNotImplemented: 501,
}


def _http_error(exc: VfsError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(type(exc), 500), detail=exc.message
    )


@router.get("/stat", response_model=Stat)
def stat(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> Stat:
    return WikisourceVfs(session).stat(path)


@router.post("/stat/bulk", response_model=StatBulkResponse)
def stat_bulk(
    body: StatBulkRequest,
    session: Session = Depends(get_session),
) -> StatBulkResponse:
    """Batched stat() for refresh() sweeps over many cached paths at once.
    Results are in request order — index i answers paths[i]."""
    return StatBulkResponse(results=WikisourceVfs(session).stat_bulk(body.paths))


@router.get("/children", response_model=ListChildrenResponse)
def list_children(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> ListChildrenResponse:
    """VFS getChildren(). Pure cache reads — never triggers a wiki fetch."""
    try:
        return WikisourceVfs(session).list_children(path)
    except VfsError as exc:
        raise _http_error(exc) from exc


@router.get("/content", response_model=ReadContentResponse)
def read_content(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> ReadContentResponse:
    try:
        return WikisourceVfs(session).read(path)
    except VfsError as exc:
        raise _http_error(exc) from exc


@router.post("/content", response_model=WriteResult)
def write_content(
    req: WriteContentRequest,
    session: Session = Depends(get_session),
) -> WriteResult:
    """Local save only — appends to the edit journal and marks the page
    dirty; the wiki is untouched until the commit worker pushes. A base_revid
    mismatch against the cached remote revid returns status='conflict'."""
    return WikisourceVfs(session).write(req)


@router.post("/rename", response_model=OperationResult)
def rename(req: RenameRequest) -> OperationResult:
    return OperationResult(
        status=OperationStatus.unsupported, message="rename not yet implemented"
    )


@router.post("/delete", response_model=OperationResult)
def delete(req: DeleteRequest) -> OperationResult:
    return OperationResult(
        status=OperationStatus.unsupported, message="delete not supported"
    )


@router.post("/child", response_model=OperationResult)
def create_child(req: CreateChildRequest) -> OperationResult:
    return OperationResult(
        status=OperationStatus.unsupported, message="create not yet implemented"
    )


@router.get("/changes", response_model=ChangesSinceResponse)
def changes_since(
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> ChangesSinceResponse:
    return ChangesSinceResponse(changes=[], next_cursor=cursor or "0", has_more=False)
