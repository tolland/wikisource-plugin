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
from wtbot.model import Site
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.vfs.store import EffectiveState, Entry, PageStore, meta_has_image

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
precomputed answer (page has no ProofreadPageMeta row), so absence needs its own
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

    def subpages(self, site: Site, title: str) -> list[Entry]:
        """Direct and nested subpages of [title]; empty when the namespace
        does not support subpages (the slash is then part of the title)."""
        if not self.subpages_enabled(site, title):
            return []
        return self.store.entries_with_title_prefix(site, f"{title}/")

    # -- per-title content operations -----------------------------------------

    def _resolve_meta(
        self, entry: Entry, meta: ProofreadPageMeta | None | object
    ) -> ProofreadPageMeta | None:
        """`meta` may be precomputed by batched callers (one metadata query
        per listing); the _UNRESOLVED default means look it up here."""
        if meta is _UNRESOLVED:
            return self.store.proofread_page_meta(entry.pk)
        return meta if isinstance(meta, ProofreadPageMeta) else None

    def page_node(
        self,
        path: str,
        entry: Entry,
        name: str | None = None,
        meta: ProofreadPageMeta | None | object = _UNRESOLVED,
        state: EffectiveState | None = None,
    ) -> Node:
        resolved = self._resolve_meta(entry, meta)
        state = state or self._state(entry, resolved)
        return Node(
            path=path,
            name=name if name is not None else entry.name,
            kind=NodeKind.file,
            stable_id=entry.pageid,
            revid=state.revid,
            timestamp=ts_millis(entry.timestamp),
            length=len(state.body.encode()),
            writable=True,
            content_model=entry.content_model,
            quality_level=resolved.quality_level if resolved is not None else None,
            dirty=entry.title.dirty,
            has_reference_image=meta_has_image(resolved),
            # A page we pushed exists remotely even if its refetch is still
            # queued, so this follows the bridged revid, not the snapshot.
            placeholder=state.placeholder,
        )

    def stat_page(
        self,
        raw_path: str,
        entry: Entry,
        name: str,
        state: EffectiveState | None = None,
        meta: ProofreadPageMeta | None | object = _UNRESOLVED,
    ) -> Stat:
        resolved = self._resolve_meta(entry, meta)
        state = state or self._state(entry, resolved)
        return Stat(
            path=raw_path,
            exists=True,
            name=name,
            kind=NodeKind.file,
            stable_id=entry.pageid,
            revid=state.revid,
            timestamp=ts_millis(entry.timestamp),
            length=len(state.body.encode()),
            content_model=entry.content_model,
            quality_level=resolved.quality_level if resolved is not None else None,
            dirty=entry.title.dirty,
            has_reference_image=meta_has_image(resolved),
            # A page we pushed exists remotely even if its refetch is still
            # queued, so this follows the bridged revid, not the snapshot.
            placeholder=state.placeholder,
        )

    def _state(self, entry: Entry, meta: ProofreadPageMeta | None) -> EffectiveState:
        return self.store.effective_state_from(
            entry,
            uncommitted_body=self.store.latest_uncommitted_body(entry.pk),
            commit=self.store.latest_successful_commits([entry.pk]).get(entry.pk),
            proposed=self.store.proposed_body(entry, meta),
        )

    def read_page(self, raw_path: str, entry: Entry) -> ReadContentResponse:
        """The effective body -- which for a title the wiki does not hold
        falls back to the proposed body, so a new transcription opens
        well-formed (see PageStore.effective_state)."""
        state = self.store.effective_state(entry)
        return ReadContentResponse(
            path=raw_path,
            revid=state.revid,
            content_base64=_b64(state.body),
        )

    def write_page(self, req: WriteContentRequest, entry: Entry) -> WriteResult:
        """Local save via the edit journal (see PageStore.append_edit and
        effective_state for the Page.text discipline). A base_revid mismatch
        against the cached remote revid is an edit conflict, not an error.

        The comparison is against the *effective* revid, the same value stat
        and read report. Against the raw snapshot it would reject a save based
        on a revision we ourselves pushed but have not refetched yet -- the
        client would be told it conflicts with our own edit."""
        revid = self.store.effective_state(entry).revid
        if req.base_revid is not None and revid is not None and req.base_revid != revid:
            return WriteResult(
                path=req.path,
                status=WriteStatus.conflict,
                new_revid=revid,
                message=f"remote revid is {revid}, edit was based on {req.base_revid}",
            )

        self.store.append_edit(
            entry,
            body=base64.b64decode(req.content_base64).decode(),
            base_revid=req.base_revid if req.base_revid is not None else revid,
            comment=req.comment,
        )

        # Local save succeeds without a new remote revid — the page is still
        # on that revision until the commit worker pushes it.
        return WriteResult(path=req.path, status=WriteStatus.ok, new_revid=revid)
