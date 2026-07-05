import base64
from datetime import datetime, timezone

from wtbot.api.schemas import (
    Node,
    NodeKind,
    ReadContentResponse,
    Stat,
    WriteContentRequest,
    WriteResult,
    WriteStatus,
)
from wtbot.model import Page, Site
from wtbot.vfs.store import PageStore

"""mediawiki:// — the title-addressed layer.

Knows pages, namespaces, and subpage semantics; knows nothing about
ProofreadPage or the wikisource:// synthetic tree. The wikisource overlay
maps its synthetic paths down to titles and delegates content operations
(stat/read/write of one page, subpage enumeration) here. A vanilla
mediawiki:// path surface (`/{family}/{code}/{title}`) can later be mounted
directly on this object.

Subpage rule: in a namespace with subpages enabled, `Foo/Bar` is a child
node of `Foo`; otherwise the slash is just part of a flat title. The flag
comes from the per-site Namespace map (populated from siteinfo). When the
namespace is unknown — fixtures, or a cache that has pages but no siteinfo
fetch yet — the rule is permissive: we cannot rule subpages out, and the
overlay's Index assets (styles.css) depend on being visible.
"""


def ts_millis(dt: datetime | None) -> str | None:
    """Milliseconds-since-epoch string for VirtualFile.getTimeStamp()."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def _b64(body: str) -> str:
    return base64.b64encode(body.encode()).decode()


def title_namespace_name(title: str) -> str:
    """The namespace prefix of a title ('' for the main namespace). Whether
    the prefix is a *real* namespace is decided against the site's Namespace
    map, not here — a mainspace title like 'Faust: Part One' simply won't
    match one."""
    prefix, sep, _ = title.partition(":")
    return prefix if sep else ""


class MediaWikiVfs:
    def __init__(self, store: PageStore) -> None:
        self.store = store

    # -- subpages -----------------------------------------------------------

    def subpages_enabled(self, site: Site, title: str) -> bool:
        ns = self.store.namespace_by_name(site, title_namespace_name(title))
        if ns is None:
            return True  # permissive until siteinfo populates the map
        return ns.subpages

    def subpages(self, site: Site, title: str) -> list[Page]:
        """Direct and nested subpages of [title]; empty when the namespace
        does not support subpages (the slash is then part of the title)."""
        if not self.subpages_enabled(site, title):
            return []
        return self.store.pages_with_title_prefix(site, f"{title}/")

    # -- per-page content operations ------------------------------------------

    def page_node(
        self,
        path: str,
        page: Page,
        name: str | None = None,
        has_image: bool | None = None,
    ) -> Node:
        """`has_image` may be precomputed by batched callers (one PageMeta
        query per listing); None means look it up here."""
        body = self.store.effective_body(page)
        if has_image is None:
            has_image = self.store.has_page_image(page)
        return Node(
            path=path,
            name=name if name is not None else page.title,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=page.revid,
            timestamp=ts_millis(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            writable=True,
            content_model=page.content_model,
            quality_level=page.quality_level,
            dirty=page.dirty,
            has_page_image=has_image,
            placeholder=page.revid is None,
        )

    def stat_page(
        self,
        raw_path: str,
        page: Page,
        name: str,
        body: str | None = None,
        has_image: bool | None = None,
    ) -> Stat:
        if body is None:
            body = self.store.effective_body(page)
        if has_image is None:
            has_image = self.store.has_page_image(page)
        return Stat(
            path=raw_path,
            exists=True,
            name=name,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=page.revid,
            timestamp=ts_millis(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            content_model=page.content_model,
            quality_level=page.quality_level,
            dirty=page.dirty,
            has_page_image=has_image,
            placeholder=page.revid is None,
        )

    def read_page(
        self, raw_path: str, page: Page, default_body: str | None = None
    ) -> ReadContentResponse:
        """`default_body` is served when the page has no body at all (a
        placeholder stub with no local edits) — the overlay passes the
        content-model scaffold so a new transcription opens well-formed."""
        body = self.store.effective_body(page)
        if not body and default_body is not None:
            body = default_body
        return ReadContentResponse(
            path=raw_path,
            revid=page.revid,
            content_base64=_b64(body),
        )

    def write_page(self, req: WriteContentRequest, page: Page) -> WriteResult:
        """Local save via the edit journal (see PageStore.append_edit and
        effective_body for the Page.text discipline). A base_revid mismatch
        against the cached remote revid is an edit conflict, not an error."""
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

        self.store.append_edit(
            page,
            body=base64.b64decode(req.content_base64).decode(),
            base_revid=req.base_revid if req.base_revid is not None else page.revid,
            comment=req.comment,
        )

        # Local save succeeds without a new remote revid — the page is still
        # on page.revid until the commit worker pushes it.
        return WriteResult(path=req.path, status=WriteStatus.ok, new_revid=page.revid)
