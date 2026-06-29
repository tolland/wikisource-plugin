"""VFS read endpoints — surface A.

Path scheme (all relative to wikisource://):

  /                                       root — all sites
  /{family}/{code}/                       site root — Index pages for that site
  /{family}/{code}/{Index title}/         index dir — Pages + File subdir
  /{family}/{code}/{Index title}/{Page title}        page wikitext file
  /{family}/{code}/{Index title}/{File title}/       file dir
  /{family}/{code}/{Index title}/{File title}/wikitext   File: description wikitext
  /{family}/{code}/{Index title}/{File title}/blob       binary (stub — 501)

Write / rename / delete and the change feed are stubbed for now.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.api.schemas import (
    ChangesSinceResponse,
    CreateChildRequest,
    DeleteRequest,
    ListChildrenResponse,
    Node,
    NodeKind,
    OperationResult,
    OperationStatus,
    ReadContentResponse,
    RenameRequest,
    Stat,
    WriteContentRequest,
    WriteResult,
    WriteStatus,
)
from wtbot.deps import get_session
from wtbot.sqlmodel import FileBlob, Page, Site
from wtbot.sqlmodel.namespace import NsRole

router = APIRouter(prefix="/vfs", tags=["vfs"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ts(dt: datetime | None) -> str | None:
    """Milliseconds-since-epoch string for VirtualFile.getTimeStamp()."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def _page_node(path: str, page: Page) -> Node:
    body = page.body or ""
    return Node(
        path=path,
        name=page.title,
        kind=NodeKind.file,
        stable_id=page.pageid,
        revid=page.revid,
        timestamp=_ts(page.local_modified_at or page.remote_timestamp),
        length=len(body.encode()),
        writable=True,
    )


def _dir_node(path: str, name: str, stable_id: int | None = None) -> Node:
    return Node(
        path=path,
        name=name,
        kind=NodeKind.directory,
        stable_id=stable_id,
        writable=False,
    )


def _blob_node(path: str, blob: FileBlob | None) -> Node:
    return Node(
        path=path,
        name="blob",
        kind=NodeKind.file,
        length=blob.size if blob else None,
        writable=False,
    )


def _parse_path(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _get_site(session: Session, family: str, code: str) -> Site:
    site = session.exec(
        select(Site).where(Site.family == family, Site.code == code)
    ).first()
    if site is None:
        raise HTTPException(status_code=404, detail=f"site {family}/{code} not found")
    return site


def _index_to_file_title(index_title: str) -> str:
    _, _, rest = index_title.partition(":")
    return f"File:{rest}"


# ---------------------------------------------------------------------------
# A) stat
# ---------------------------------------------------------------------------


@router.get("/stat", response_model=Stat)
def stat(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> Stat:
    parts = _parse_path(path)

    if not parts:
        return Stat(path=path, exists=True, kind=NodeKind.directory)

    if len(parts) < 2:
        return Stat(path=path, exists=False)

    if len(parts) == 2:
        family, code = parts
        exists = (
            session.exec(
                select(Site).where(Site.family == family, Site.code == code)
            ).first()
            is not None
        )
        return Stat(
            path=path, exists=exists, kind=NodeKind.directory if exists else None
        )

    family, code, index_title = parts[0], parts[1], parts[2]
    rest = parts[3:]

    site = session.exec(
        select(Site).where(Site.family == family, Site.code == code)
    ).first()
    if site is None:
        return Stat(path=path, exists=False)

    index_page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == index_title)
    ).first()
    if index_page is None:
        return Stat(path=path, exists=False)

    if not rest:
        return Stat(
            path=path,
            exists=True,
            kind=NodeKind.directory,
            stable_id=index_page.pageid,
            revid=index_page.revid,
            timestamp=_ts(index_page.local_modified_at or index_page.remote_timestamp),
        )

    # Synthetic leaf nodes: last segment is "wikitext" or "blob" and the preceding
    # segments form a File: title (e.g. rest = ["File:Foo.djvu", "wikitext"])
    if rest[-1] in ("wikitext", "blob") and "/".join(rest[:-1]).startswith("File:"):
        file_title = "/".join(rest[:-1])
        leaf = rest[-1]
        file_page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if file_page is None:
            return Stat(path=path, exists=False)
        if leaf == "wikitext":
            body = file_page.body or ""
            return Stat(
                path=path,
                exists=True,
                kind=NodeKind.file,
                stable_id=file_page.pageid,
                revid=file_page.revid,
                timestamp=_ts(
                    file_page.local_modified_at or file_page.remote_timestamp
                ),
                length=len(body.encode()),
            )
        blob = session.exec(
            select(FileBlob).where(FileBlob.page_pk == file_page.pk)
        ).first()
        return Stat(
            path=path,
            exists=True,
            kind=NodeKind.file,
            length=blob.size if blob else None,
        )

    child_title = "/".join(rest)

    # File: title → directory node
    if child_title.startswith("File:"):
        fp = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == child_title)
        ).first()
        exists = fp is not None
        return Stat(
            path=path,
            exists=exists,
            kind=NodeKind.directory if exists else None,
            stable_id=fp.pageid if fp else None,
        )

    # Page: or other wikitext title
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == child_title)
    ).first()
    if page is None:
        return Stat(path=path, exists=False)
    body = page.body or ""
    return Stat(
        path=path,
        exists=True,
        kind=NodeKind.file,
        stable_id=page.pageid,
        revid=page.revid,
        timestamp=_ts(page.local_modified_at or page.remote_timestamp),
        length=len(body.encode()),
    )


# ---------------------------------------------------------------------------
# A) list_children
# ---------------------------------------------------------------------------


@router.get("/children", response_model=ListChildrenResponse)
def list_children(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> ListChildrenResponse:
    """VFS getChildren(). Pure cache reads — never triggers a wiki fetch."""
    parts = _parse_path(path)
    norm = "/" + "/".join(parts) if parts else "/"

    # / → sites
    if not parts:
        sites = session.exec(select(Site)).all()
        return ListChildrenResponse(
            parent_path=norm,
            children=[
                _dir_node(f"/{s.family}/{s.code}", f"{s.family}/{s.code}")
                for s in sites
            ],
        )

    # /{family}/{code} → Index pages
    if len(parts) == 2:
        family, code = parts
        site = _get_site(session, family, code)
        indexes = session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.index,
            )
        ).all()
        return ListChildrenResponse(
            parent_path=norm,
            children=[
                _dir_node(f"{norm}/{p.title}", p.title, stable_id=p.pageid)
                for p in indexes
            ],
        )

    family, code, index_title = parts[0], parts[1], parts[2]
    rest = parts[3:]
    site = _get_site(session, family, code)
    index_path = f"/{family}/{code}/{index_title}"

    index_page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == index_title)
    ).first()
    if index_page is None:
        raise HTTPException(status_code=404, detail=f"index not found: {index_title}")

    # /{family}/{code}/{Index title} → child Pages + File: subdir
    if not rest:
        children: list[Node] = []

        pages = session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.page,
                Page.index_title == index_title,
            )
        ).all()
        for p in sorted(pages, key=lambda p: p.page_number or 0):
            children.append(_page_node(f"{index_path}/{p.title}", p))

        file_title = _index_to_file_title(index_title)
        file_page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if file_page is not None:
            children.append(
                _dir_node(
                    f"{index_path}/{file_title}", file_title, stable_id=file_page.pageid
                )
            )

        return ListChildrenResponse(parent_path=index_path, children=children)

    # /{family}/{code}/{Index title}/{File title} → wikitext + blob
    # rest is the File: title segments (may be multi-part if File title has slashes,
    # but in practice Wikisource File titles don't contain slashes)
    file_title = "/".join(rest)
    if file_title.startswith("File:"):
        file_page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if file_page is None:
            raise HTTPException(
                status_code=404, detail=f"file page not found: {file_title}"
            )
        blob = session.exec(
            select(FileBlob).where(FileBlob.page_pk == file_page.pk)
        ).first()
        file_dir_path = f"{index_path}/{file_title}"
        wikitext = _page_node(f"{file_dir_path}/wikitext", file_page)
        wikitext.name = "wikitext"
        return ListChildrenResponse(
            parent_path=file_dir_path,
            children=[wikitext, _blob_node(f"{file_dir_path}/blob", blob)],
        )

    raise HTTPException(status_code=404, detail=f"not a directory: {path}")


# ---------------------------------------------------------------------------
# A) read_content
# ---------------------------------------------------------------------------


@router.get("/content", response_model=ReadContentResponse)
def read_content(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> ReadContentResponse:
    parts = _parse_path(path)
    if len(parts) < 4:
        raise HTTPException(status_code=400, detail="path does not refer to a file")

    family, code, _index_title = parts[0], parts[1], parts[2]
    rest = parts[3:]
    site = _get_site(session, family, code)
    # Detect synthetic "wikitext" / "blob" leaf under File: dir
    if rest[-1] in ("wikitext", "blob") and "/".join(rest[:-1]).startswith("File:"):
        file_title = "/".join(rest[:-1])
        if rest[-1] == "blob":
            raise HTTPException(
                status_code=501, detail="blob streaming not yet implemented"
            )
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if page is None:
            raise HTTPException(
                status_code=404, detail=f"file page not found: {file_title}"
            )
        body = (page.body or "").encode()
        return ReadContentResponse(
            path=path,
            revid=page.revid,
            content_base64=base64.b64encode(body).decode(),
        )

    child_title = "/".join(rest)
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == child_title)
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail=f"page not found: {child_title}")
    body = (page.body or "").encode()
    return ReadContentResponse(
        path=path,
        revid=page.revid,
        content_base64=base64.b64encode(body).decode(),
    )


# ---------------------------------------------------------------------------
# Write / mutate — stubbed
# ---------------------------------------------------------------------------


@router.post("/content", response_model=WriteResult)
def write_content(req: WriteContentRequest) -> WriteResult:
    return WriteResult(
        path=req.path, status=WriteStatus.error, message="write not yet implemented"
    )


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


# ---------------------------------------------------------------------------
# B) Change feed — stub
# ---------------------------------------------------------------------------


@router.get("/changes", response_model=ChangesSinceResponse)
def changes_since(
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> ChangesSinceResponse:
    return ChangesSinceResponse(changes=[], next_cursor=cursor or "0", has_more=False)
