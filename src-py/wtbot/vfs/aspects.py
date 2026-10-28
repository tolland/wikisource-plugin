from __future__ import annotations

from pydantic import BaseModel

from wtbot.vfs.nodes import TitleNode
from wtbot.vfs.store import Entry, PageStore

"""The non-content aspects of a title. `wikitext` is the page body and lives
in the mediawiki layer; this module renders the read-only `props` view."""

PROPS_CONTENT_MODEL = "json"


class TitleProps(BaseModel):
    """What the cache knows about a title, as one JSON document. Read-only: it
    is a view of state that other operations (fetch, commit, journal) own."""

    title: str
    namespace: str
    content_model: str
    namespace_key: int | None
    pageid: int | None
    revid: int | None
    dirty: bool
    held_by_wiki: bool
    fetch_status: str
    index: str | None = None
    page_number: int | None = None
    quality_level: int | None = None


def title_props(store: PageStore, node: TitleNode, entry: Entry) -> TitleProps:
    state = store.effective_state(entry)
    meta = store.proofread_page_meta(entry.pk)
    index = store.index_of(entry) if meta is not None else None
    return TitleProps(
        title=entry.name,
        namespace=node.ns.name,
        content_model=entry.content_model,
        namespace_key=entry.title.namespace_key,
        pageid=entry.pageid,
        revid=state.revid,
        dirty=entry.title.dirty,
        held_by_wiki=entry.page is not None,
        fetch_status=entry.title.fetch_status.value,
        index=index.name if index is not None else None,
        page_number=meta.page_number if meta is not None else None,
        quality_level=meta.quality_level if meta is not None else None,
    )


def props_body(store: PageStore, node: TitleNode, entry: Entry) -> str:
    return title_props(store, node, entry).model_dump_json(indent=2) + "\n"
