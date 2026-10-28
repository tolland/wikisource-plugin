from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.errors import ApiError
from wtbot.api.schemas import (
    DeleteResponse,
    ListChildrenResponse,
    ReadContentResponse,
    Stat,
    StatBulkRequest,
    StatBulkResponse,
    WriteContentRequest,
    WriteResult,
)
from wtbot.deps import get_session
from wtbot.vfs import WikisourceVfs
from wtbot.vfs.errors import (
    DeleteBlocked,
    NotADirectory,
    NotAFile,
    NotDeletable,
    NotFound,
    VfsError,
)

"""VFS endpoints — thin HTTP adapter over `wtbot.vfs`.

Path scheme (all relative to wikisource://):

  /                                       root — all sites
  /{family}/{code}                        site — the namespaces that hold titles
  /{family}/{code}/{namespace}            namespace container (`(Main)` for main)
  /{family}/{code}/{ns}/{title segments}  a title: a directory holding its
                                          subpages and its aspect files
  .../{title}/@wikitext                   the title's content (what you edit)
  .../{title}/@props                      its properties, read-only JSON
  .../{Index title}/@pages                the Page: titles the Index paginates

A title is a node, not a file: it can be a page, a container of subpages, or
both, and offers any number of aspects (`aspects` on its node, default first).
Whether a slash in a title is a subpage separator is the namespace's
`subpages` flag, so `Page:Foo.djvu/8` is `/Page/Foo.djvu/8` (one title) while
`Book:A/B` is `B` under `A`. `A` is a synthetic node when nothing holds it.

All tree/classification logic lives in `wtbot.vfs`; this module only parses
params, delegates, and maps domain errors to HTTP status codes.

Served here: stat (single + bulk), children, read, write (read and write act on
aspect files; a bare title path is a directory), delete. Rename,
create-child and the change feed are designed but not implemented, and are
deliberately absent from the routing table rather than present as
always-"unsupported" answers.
"""

router = APIRouter(prefix="/vfs", tags=["vfs"], route_class=DebugLoggingRoute)

_ERROR_STATUS: dict[type[VfsError], tuple[int, str]] = {
    NotFound: (404, "not-found"),
    NotADirectory: (404, "not-a-directory"),
    NotAFile: (400, "not-a-file"),
    NotDeletable: (400, "not-deletable"),
    DeleteBlocked: (409, "delete-blocked"),
}


def _http_error(exc: VfsError) -> ApiError:
    status, code = _ERROR_STATUS.get(type(exc), (500, "vfs-error"))
    return ApiError(status_code=status, detail=exc.message, code=code)


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


@router.delete("/node", response_model=DeleteResponse)
def delete_node(
    path: str = Query(...),
    recursive: bool = Query(False),
    discard_local_edits: bool = Query(False),
    dry_run: bool = Query(False),
    session: Session = Depends(get_session),
) -> DeleteResponse:
    """Remove a title from the local cache; the wiki is untouched.

    Like MediaWiki's page delete, the default removes only the node: its
    subpages stay. `recursive` takes the subtree with it -- subpages, and for
    an Index the Page: titles it paginates. Refused (409) when a deleted title
    has uncommitted local edits (unless `discard_local_edits`) or when a title
    that stays still references one that goes. Any known title is addressable,
    including ones the synthetic tree cannot place. `dry_run` runs every check
    and reports what would go, deleting nothing."""
    try:
        return WikisourceVfs(session).delete(
            path,
            recursive=recursive,
            discard_local_edits=discard_local_edits,
            dry_run=dry_run,
        )
    except VfsError as exc:
        raise _http_error(exc) from exc


# Not served: rename, create-child, and the change feed. Each had a
# route that unconditionally answered "unsupported" (or an empty change
# list), which put unimplemented operations in the OpenAPI spec as if
# they were contract. The request/response schemas survive in
# wtbot.api.schemas as the design record — see its "Reserved" section, which
# carries the rename-identity invariant these routes will have to honour.
