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
from wtbot.model.wikisource.page_meta import PageMeta
from wtbot.vfs.store import EffectiveState, PageStore, meta_has_image

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


_UNRESOLVED = object()
"""Sentinel default for the `meta` parameters below: None is a legitimate
precomputed answer (page has no PageMeta row), so absence needs its own
marker."""


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

    def _resolve_meta(
        self, page: Page, meta: PageMeta | None | object
    ) -> PageMeta | None:
        """`meta` may be precomputed by batched callers (one PageMeta query
        per listing); the _UNRESOLVED default means look it up here."""
        if meta is _UNRESOLVED:
            return self.store.page_meta(page)
        return meta if isinstance(meta, PageMeta) else None

    def page_node(
        self,
        path: str,
        page: Page,
        name: str | None = None,
        meta: PageMeta | None | object = _UNRESOLVED,
        state: EffectiveState | None = None,
    ) -> Node:
        state = state or self.store.effective_state(page)
        body = state.body
        resolved = self._resolve_meta(page, meta)
        return Node(
            path=path,
            name=name if name is not None else page.title,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=state.revid,
            timestamp=ts_millis(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            writable=True,
            content_model=page.content_model,
            quality_level=resolved.quality_level if resolved is not None else None,
            dirty=page.dirty,
            has_reference_image=meta_has_image(resolved),
            # A page we pushed exists remotely even if its refetch is still
            # queued, so this follows the bridged revid, not the snapshot.
            placeholder=state.placeholder,
        )

    def stat_page(
        self,
        raw_path: str,
        page: Page,
        name: str,
        state: EffectiveState | None = None,
        meta: PageMeta | None | object = _UNRESOLVED,
    ) -> Stat:
        state = state or self.store.effective_state(page)
        body = state.body
        resolved = self._resolve_meta(page, meta)
        return Stat(
            path=raw_path,
            exists=True,
            name=name,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=state.revid,
            timestamp=ts_millis(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            content_model=page.content_model,
            quality_level=resolved.quality_level if resolved is not None else None,
            dirty=page.dirty,
            has_reference_image=meta_has_image(resolved),
            # A page we pushed exists remotely even if its refetch is still
            # queued, so this follows the bridged revid, not the snapshot.
            placeholder=state.placeholder,
        )

    def read_page(
        self, raw_path: str, page: Page, default_body: str | None = None
    ) -> ReadContentResponse:
        """`default_body` is served when the page has no body at all (a
        placeholder stub with no local edits) — the overlay passes the
        content-model scaffold so a new transcription opens well-formed."""
        state = self.store.effective_state(page)
        body = state.body or (default_body or "")
        return ReadContentResponse(
            path=raw_path,
            revid=state.revid,
            content_base64=_b64(body),
        )

    def write_page(self, req: WriteContentRequest, page: Page) -> WriteResult:
        """Local save via the edit journal (see PageStore.append_edit and
        effective_state for the Page.text discipline). A base_revid mismatch
        against the cached remote revid is an edit conflict, not an error.

        The comparison is against the *effective* revid, the same value stat
        and read report. Against the raw snapshot it would reject a save based
        on a revision we ourselves pushed but have not refetched yet -- the
        client would be told it conflicts with our own edit."""
        revid = self.store.effective_state(page).revid
        if req.base_revid is not None and revid is not None and req.base_revid != revid:
            return WriteResult(
                path=req.path,
                status=WriteStatus.conflict,
                new_revid=revid,
                message=f"remote revid is {revid}, edit was based on {req.base_revid}",
            )

        self.store.append_edit(
            page,
            body=base64.b64decode(req.content_base64).decode(),
            base_revid=req.base_revid if req.base_revid is not None else revid,
            comment=req.comment,
        )

        # Local save succeeds without a new remote revid — the page is still
        # on that revision until the commit worker pushes it.
        return WriteResult(path=req.path, status=WriteStatus.ok, new_revid=revid)
