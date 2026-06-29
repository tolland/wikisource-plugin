from fastapi import APIRouter, Query

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
    WriteContentRequest,
    WriteResult,
)

"""
FastAPI routes for the VFS contract. Stubs only -- bodies raise NotImplemented
or return placeholder data. The point of this file is the *signatures*: FastAPI
emits the OpenAPI spec from them, and the Kotlin client is generated off that.

Wire into the app in main.py with:
    from wtbot.api.routes import router as vfs_router
    app.include_router(vfs_router)

All routes are local (loopback / unix socket); the plugin treats them as fast.
If any single route is too slow under profiling (likely list_children /
read_content during indexing), that one route can be bypassed with direct JDBC
on the Kotlin side without changing this contract.
"""


router = APIRouter(prefix="/vfs", tags=["vfs"])


# --- A) Operations -------------------------------------------------------
@router.get("/children", response_model=ListChildrenResponse)
def list_children(path: str = Query(..., description="Parent node path")) -> ListChildrenResponse:
    """VFS getChildren(). Reads cached rows from SQLite; does not fetch from wiki."""
    raise NotImplementedError


@router.get("/content", response_model=ReadContentResponse)
def read_content(path: str = Query(...)) -> ReadContentResponse:
    """VFS contentsToByteArray()/getInputStream()."""
    raise NotImplementedError


@router.get("/stat", response_model=Stat)
def stat(path: str = Query(...)) -> Stat:
    """Cheap metadata probe -- timestamp/length/revid/exists without body."""
    raise NotImplementedError


@router.post("/content", response_model=WriteResult)
def write_content(req: WriteContentRequest) -> WriteResult:
    """VFS setBinaryContent(). Enqueues a commit; conflict surfaced in status."""
    raise NotImplementedError


@router.post("/rename", response_model=OperationResult)
def rename(req: RenameRequest) -> OperationResult:
    """VFS renameFile(). On the wiki this is a page move via pywikibot."""
    raise NotImplementedError


@router.post("/delete", response_model=OperationResult)
def delete(req: DeleteRequest) -> OperationResult:
    """VFS deleteFile(). Likely returns status=unsupported for most namespaces."""
    return OperationResult(status=OperationStatus.unsupported, message="delete not supported yet")


@router.post("/child", response_model=OperationResult)
def create_child(req: CreateChildRequest) -> OperationResult:
    """VFS createChildFile()/createChildDirectory()."""
    raise NotImplementedError


# --- B) Change feed ------------------------------------------------------
@router.get("/changes", response_model=ChangesSinceResponse)
def changes_since(
    cursor: str | None = Query(None, description="Opaque cursor from previous poll; None = from start"),
    limit: int = Query(100, ge=1, le=1000),
) -> ChangesSinceResponse:
    """Poll endpoint driving the plugin's refresh loop. Renames/moves are
    reported with old_path + stable_id so the plugin preserves node identity."""
    raise NotImplementedError
