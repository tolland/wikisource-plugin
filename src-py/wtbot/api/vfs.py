import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.api.debug_loggig_route import DebugLoggingRoute
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
    StatBulkRequest,
    StatBulkResponse,
    WriteContentRequest,
    WriteResult,
    WriteStatus,
)
from wtbot.deps import get_session
from wtbot.model import EditJournal, FileBlob, Page, Site
from wtbot.model.namespace import NsRole

"""VFS read endpoints — surface A.

Path scheme (all relative to wikisource://):

  /                                       root — all sites
  /{family}/{code}/                       site root — Index pages for that site
  /{family}/{code}/{Index title}/         index dir — Pages + File subdir
  /{family}/{code}/{Index title}/wikitext            Index: description/pagelist wikitext
  /{family}/{code}/{Index title}/{Page title}        page wikitext file
  /{family}/{code}/{Index title}/{File title}/       file dir
  /{family}/{code}/{Index title}/{File title}/wikitext   File: description wikitext
  /{family}/{code}/{Index title}/{File title}/blob       binary (stub — 501)

Write / rename / delete and the change feed are stubbed for now.
"""

router = APIRouter(prefix="/vfs", tags=["vfs"], route_class=DebugLoggingRoute)

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


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


def _effective_body(session: Session, page: Page) -> str:
    """The body read_content()/stat() should report for [page].

    Page.text is the cached *remote* body -- written only by the fetch
    worker on refresh from the wiki. Local IDE saves must never touch it, or
    it stops meaning "what's on the wiki" and a refresh silently loses the
    diff base. Instead, a save appends an EditJournal row; this reads the
    most recent uncommitted one back, falling back to Page.text when there's
    nothing uncommitted (never edited locally, or already pushed and
    marked committed).
    """
    latest = session.exec(
        select(EditJournal)
        .where(EditJournal.page_pk == page.pk)
        .where(EditJournal.committed == False)  # noqa: E712
        .order_by(EditJournal.saved_at.desc())
        .limit(1)
    ).first()
    if latest is not None:
        return latest.body
    return page.text or ""


def _latest_uncommitted_bodies(session: Session, page_pks: list[int]) -> dict[int, str]:
    """Batched form of [_effective_body]'s EditJournal lookup, for call sites
    (stat_bulk) that already batch their Page query and shouldn't regress to
    one EditJournal query per page."""
    if not page_pks:
        return {}
    rows = session.exec(
        select(EditJournal)
        .where(EditJournal.page_pk.in_(page_pks))
        .where(EditJournal.committed == False)  # noqa: E712
        .order_by(EditJournal.saved_at)
    ).all()
    # Rows are ascending by saved_at, so the last write per page_pk wins.
    return {row.page_pk: row.body for row in rows}


def _page_node(session: Session, path: str, page: Page) -> Node:
    body = _effective_body(session, page)
    return Node(
        path=path,
        name=page.title,
        kind=NodeKind.file,
        stable_id=page.pageid,
        revid=page.revid,
        timestamp=_ts(page.local_modified_at or page.remote_timestamp),
        length=len(body.encode()),
        writable=True,
        content_model=page.content_model,
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
        stable_id=None,
        revid=None,
        content_model=None,
        timestamp=None,
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


def _index_asset_title(index_title: str, rest: list[str]) -> str:
    return f"{index_title}/{'/'.join(rest)}"


def _index_asset_name(index_title: str, title: str) -> str:
    prefix = f"{index_title}/"
    if title.startswith(prefix):
        return title[len(prefix) :]
    return title


def _index_asset_node(
    session: Session, index_path: str, index_title: str, page: Page
) -> Node:
    name = _index_asset_name(index_title, page.title)
    node = _page_node(session, f"{index_path}/{name}", page)
    node.name = name
    return node


def _get_index_asset(
    session: Session, site: Site, index_title: str, rest: list[str]
) -> Page | None:
    if not rest:
        return None
    asset_title = _index_asset_title(index_title, rest)
    return session.exec(
        select(Page).where(
            Page.site_pk == site.pk,
            Page.title == asset_title,
            Page.content_model != PROOFREAD_INDEX_CONTENT_MODEL,
        )
    ).first()


# ---------------------------------------------------------------------------
# A) stat
# ---------------------------------------------------------------------------


@router.get("/stat", response_model=Stat)
def stat(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> Stat:
    return _stat_one(session, path)


def _stat_one(session: Session, path: str) -> Stat:
    parts = _parse_path(path)

    if not parts:
        return Stat(path=path, exists=True, name="/", kind=NodeKind.directory)

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
            path=path,
            exists=exists,
            name=f"{family}/{code}" if exists else None,
            kind=NodeKind.directory if exists else None,
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
            name=index_title,
            kind=NodeKind.directory,
            stable_id=index_page.pageid,
            revid=index_page.revid,
            timestamp=_ts(index_page.local_modified_at or index_page.remote_timestamp),
            content_model=index_page.content_model,
        )

    container = rest[0]

    # Index's own wikitext body (dual role: directory + proofread-index content)
    if container == "wikitext" and len(rest) == 1:
        body = _effective_body(session, index_page)
        return Stat(
            path=path,
            exists=True,
            name="wikitext",
            kind=NodeKind.file,
            stable_id=index_page.pageid,
            revid=index_page.revid,
            timestamp=_ts(index_page.local_modified_at or index_page.remote_timestamp),
            length=len(body.encode()),
            content_model=index_page.content_model,
        )

    # Pages/ container or individual page beneath it
    if container == "Pages":
        if len(rest) == 1:
            return Stat(path=path, exists=True, name="Pages", kind=NodeKind.directory)
        page_title = "/".join(rest[1:])
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == page_title)
        ).first()
        if page is None:
            return Stat(path=path, exists=False)
        body = _effective_body(session, page)
        return Stat(
            path=path,
            exists=True,
            name=page.title,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=page.revid,
            timestamp=_ts(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            content_model=page.content_model,
        )

    # Stub containers
    if container in ("Templates", "TranscludedFiles"):
        return Stat(path=path, exists=True, name=container, kind=NodeKind.directory)

    # File: directory or wikitext/blob leaf beneath it
    file_title = "/".join(rest)
    if rest[-1] in ("wikitext", "blob") and "/".join(rest[:-1]).startswith("File:"):
        file_title = "/".join(rest[:-1])
        leaf = rest[-1]
        file_page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if file_page is None:
            return Stat(path=path, exists=False)
        if leaf == "wikitext":
            body = _effective_body(session, file_page)
            return Stat(
                path=path,
                exists=True,
                name="wikitext",
                kind=NodeKind.file,
                stable_id=file_page.pageid,
                revid=file_page.revid,
                timestamp=_ts(
                    file_page.local_modified_at or file_page.remote_timestamp
                ),
                length=len(body.encode()),
                content_model=file_page.content_model,
            )
        blob = session.exec(
            select(FileBlob).where(FileBlob.page_pk == file_page.pk)
        ).first()
        return Stat(
            path=path,
            exists=True,
            name="blob",
            kind=NodeKind.file,
            length=blob.size if blob else None,
        )

    if file_title.startswith("File:"):
        fp = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        exists = fp is not None
        return Stat(
            path=path,
            exists=exists,
            name=file_title if exists else None,
            kind=NodeKind.directory if exists else None,
            stable_id=fp.pageid if fp else None,
        )

    asset_page = _get_index_asset(session, site, index_title, rest)
    if asset_page is not None:
        body = _effective_body(session, asset_page)
        return Stat(
            path=path,
            exists=True,
            name=_index_asset_name(index_title, asset_page.title),
            kind=NodeKind.file,
            stable_id=asset_page.pageid,
            revid=asset_page.revid,
            timestamp=_ts(asset_page.local_modified_at or asset_page.remote_timestamp),
            length=len(body.encode()),
            content_model=asset_page.content_model,
        )

    return Stat(path=path, exists=False)


@router.post("/stat/bulk", response_model=StatBulkResponse)
def stat_bulk(
    body: StatBulkRequest,
    session: Session = Depends(get_session),
) -> StatBulkResponse:
    """Batched stat() for refresh() sweeps over many cached paths at once.

    Page-under-Pages/ paths (the dominant case at real-library scale — one
    query per site+index_title rather than one per page) are batched via
    `Page.title.in_(...)`; every other path shape falls back to `_stat_one`,
    since sites/indexes/file-dirs are comparatively few per session.
    """
    results: dict[int, Stat] = {}
    page_groups: dict[tuple[str, str, str], list[tuple[int, str, str]]] = {}

    for i, path in enumerate(body.paths):
        parts = _parse_path(path)
        if len(parts) >= 5 and parts[3] == "Pages":
            family, code, index_title = parts[0], parts[1], parts[2]
            page_title = "/".join(parts[4:])
            page_groups.setdefault((family, code, index_title), []).append(
                (i, path, page_title)
            )
        else:
            results[i] = _stat_one(session, path)

    for (family, code, index_title), entries in page_groups.items():
        site = session.exec(
            select(Site).where(Site.family == family, Site.code == code)
        ).first()
        if site is None:
            for i, path, _ in entries:
                results[i] = Stat(path=path, exists=False)
            continue
        titles = [page_title for _, _, page_title in entries]
        pages = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title.in_(titles))
        ).all()
        pages_by_title = {p.title: p for p in pages}
        uncommitted_bodies = _latest_uncommitted_bodies(
            session, [p.pk for p in pages if p.pk is not None]
        )
        for i, path, page_title in entries:
            page = pages_by_title.get(page_title)
            if page is None:
                results[i] = Stat(path=path, exists=False)
                continue
            body_text = uncommitted_bodies.get(page.pk, page.text or "")
            results[i] = Stat(
                path=path,
                exists=True,
                name=page.title,
                kind=NodeKind.file,
                stable_id=page.pageid,
                revid=page.revid,
                timestamp=_ts(page.local_modified_at or page.remote_timestamp),
                length=len(body_text.encode()),
                content_model=page.content_model,
            )

    return StatBulkResponse(results=[results[i] for i in range(len(body.paths))])


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
                Page.content_model == PROOFREAD_INDEX_CONTENT_MODEL,
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

    container = rest[0] if rest else None

    # /{family}/{code}/{Index title} → Pages/ + File:/ + Templates/ + TranscludedFiles/
    if not rest:
        children: list[Node] = []
        index_wikitext = _page_node(session, f"{index_path}/wikitext", index_page)
        index_wikitext.name = "wikitext"
        children.append(index_wikitext)
        children.append(_dir_node(f"{index_path}/Pages", "Pages"))

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

        index_asset_candidates = session.exec(
            select(Page)
            .where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.index,
                Page.content_model != PROOFREAD_INDEX_CONTENT_MODEL,
            )
            .order_by(Page.title)
        ).all()
        index_assets = [
            asset
            for asset in index_asset_candidates
            if asset.index_title == index_title
            or asset.title.startswith(f"{index_title}/")
        ]
        children.extend(
            _index_asset_node(session, index_path, index_title, asset)
            for asset in index_assets
        )

        children.append(_dir_node(f"{index_path}/Templates", "Templates"))
        children.append(_dir_node(f"{index_path}/TranscludedFiles", "TranscludedFiles"))
        return ListChildrenResponse(parent_path=index_path, children=children)

    # /{family}/{code}/{Index title}/Pages → sorted Page: children
    if container == "Pages":
        pages_path = f"{index_path}/Pages"
        if len(rest) == 1:
            pages = session.exec(
                select(Page).where(
                    Page.site_pk == site.pk,
                    Page.namespace_role == NsRole.page,
                    Page.index_title == index_title,
                )
            ).all()
            return ListChildrenResponse(
                parent_path=pages_path,
                children=[
                    _page_node(session, f"{pages_path}/{p.title}", p)
                    for p in sorted(pages, key=lambda p: p.page_number or 0)
                ],
            )
        # individual page under Pages/
        raise HTTPException(status_code=404, detail=f"not a directory: {path}")

    # Stub containers
    if container in ("Templates", "TranscludedFiles"):
        return ListChildrenResponse(
            parent_path=f"{index_path}/{container}", children=[]
        )

    # /{family}/{code}/{Index title}/{File title} → wikitext + blob
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
        wikitext = _page_node(session, f"{file_dir_path}/wikitext", file_page)
        wikitext.name = "wikitext"
        return ListChildrenResponse(
            parent_path=file_dir_path,
            children=[wikitext, _blob_node(f"{file_dir_path}/blob", blob)],
        )

    if _get_index_asset(session, site, index_title, rest) is not None:
        raise HTTPException(status_code=404, detail=f"not a directory: {path}")

    raise HTTPException(status_code=404, detail=f"not a directory: {path}")


# ---------------------------------------------------------------------------
# A) read_content
# ---------------------------------------------------------------------------


@router.get(
    "/content",
    response_model=ReadContentResponse,
)
def read_content(
    path: str = Query(...),
    session: Session = Depends(get_session),
) -> ReadContentResponse:
    parts = _parse_path(path)
    if len(parts) < 4:
        raise HTTPException(status_code=400, detail="path does not refer to a file")

    """
    This assumes that everything is under the /family/code/Index:SomeIndex.ext
    path system
    """
    family, code, index_title = parts[0], parts[1], parts[2]
    rest = parts[3:]
    site = _get_site(session, family, code)

    container = rest[0] if rest else None

    # synthetic container for out of tree Pages/{page title}
    if container == "Pages" and len(rest) >= 2:
        page_title = "/".join(rest[1:])
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == page_title)
        ).first()
        if page is None:
            raise HTTPException(status_code=404, detail=f"page not found: {page_title}")
        return ReadContentResponse(
            path=path,
            revid=page.revid,
            content_base64=base64.b64encode(
                _effective_body(session, page).encode()
            ).decode(),
        )

    # wikitext/blob leaf under File: dir
    if rest[-1] in ("wikitext", "blob") or "/".join(rest[:-1]).startswith("File:"):
        file_title = "/".join(rest[:-1])
        if rest[-1] == "blob":
            raise HTTPException(
                status_code=501, detail="blob streaming not yet implemented"
            )
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == index_title)
        ).first()
        if page is None:
            raise HTTPException(
                status_code=404, detail=f"file page not found: {file_title}"
            )
        return ReadContentResponse(
            path=path,
            revid=page.revid,
            content_base64=base64.b64encode(
                _effective_body(session, page).encode()
            ).decode(),
        )

    asset_page = _get_index_asset(session, site, index_title, rest)
    if asset_page is not None:
        return ReadContentResponse(
            path=path,
            revid=asset_page.revid,
            content_base64=base64.b64encode(
                _effective_body(session, asset_page).encode()
            ).decode(),
        )

    raise HTTPException(status_code=400, detail="path does not refer to a file")


# ---------------------------------------------------------------------------
# Write / mutate — stubbed
# ---------------------------------------------------------------------------


@router.post("/content", response_model=WriteResult)
def write_content(
    req: WriteContentRequest,
    session: Session = Depends(get_session),
) -> WriteResult:
    """Local save only -- appends an EditJournal row. Does not touch the wiki
    (that happens later when the commit worker drains uncommitted journal
    rows via pywikibot) and does NOT touch Page.text: that field is the
    cached *remote* body, written only by the fetch worker on refresh, and
    is the diff base for conflict detection -- overwriting it here on every
    keystroke-triggered save would silently destroy that base. read_content()
    /stat() serve the effective (edited-or-remote) body via
    _effective_body(), which reads this journal back."""
    parts = _parse_path(req.path)
    if len(parts) < 4:
        return WriteResult(
            path=req.path,
            status=WriteStatus.error,
            message="path is not a writable file",
        )

    family, code, index_title = parts[0], parts[1], parts[2]
    rest = parts[3:]

    try:
        site = _get_site(session, family, code)
    except HTTPException as exc:
        return WriteResult(path=req.path, status=WriteStatus.error, message=exc.detail)

    page_title: str | None = None
    if rest and rest[0] == "Pages" and len(rest) >= 2:
        page_title = "/".join(rest[1:])
    elif rest and rest[-1] == "wikitext":
        # wikitext is synthetic, the underlying is the parent in the path
        page_title = index_title
    elif "/".join(rest[:-1]).startswith("File:"):
        page_title = "/".join(rest[:-1])
    elif rest:
        page_title = _index_asset_title(index_title, rest)

    print(f"page_title: {page_title}")

    if page_title is None:
        return WriteResult(
            path=req.path,
            status=WriteStatus.error,
            message="path is not a writable file",
        )

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == page_title)
    ).first()
    if page is None:
        return WriteResult(
            path=req.path,
            status=WriteStatus.error,
            message=f"page not found: {page_title}",
        )

    if (
        req.base_revid is not None
        and page.revid is not None
        and req.base_revid != page.revid
    ):
        return WriteResult(
            path=req.path,
            status=WriteStatus.conflict,
            new_revid=page.revid,
            message=f"remote revid is {page.revid}, edit was based on {req.base_revid}",
        )

    body = base64.b64decode(req.content_base64).decode()

    journal = EditJournal(
        page_pk=page.pk,
        base_revid=req.base_revid if req.base_revid is not None else page.revid,
        body=body,
        comment=req.comment,
    )
    session.add(journal)

    page.dirty = True
    page.local_modified_at = datetime.now(timezone.utc)
    session.add(page)

    session.commit()

    # Local save succeeds without a new remote revid -- the page is still on
    # page.revid until the commit worker pushes it.
    return WriteResult(path=req.path, status=WriteStatus.ok, new_revid=page.revid)


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
