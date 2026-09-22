from dataclasses import dataclass

from sqlmodel import Session, select

from wtbot.model import (
    MAIN_SLOT,
    Content,
    NsRole,
    Revision,
    Slot,
    Title,
    WikiPage,
)

"""The one place that answers "what does the wiki have at this title".

Everything above this module receives a resolved object and branches on
nothing. That is the entire point of the Title/WikiPage split: the null moves
here and stops being re-derived defensively at every call site.

Two resolved shapes, because there are two questions:

- [ResolvedPage] -- a title and whatever we hold for it. What the VFS wants: it
  always has a body to serve (the head revision's, or the proposed content the
  wiki offers for an untranscribed page), so it never asks whether the page
  exists.
- [RevisedPage] -- a title with at least one cached revision, guaranteed
  non-null. What sync and promotion want: a page with no revision has nothing
  to compare and no base to replay onto, so it must not be passed to them at
  all. [require_revised] is the only way to get one, and it refuses with the
  remedy rather than returning something nullable.

Note that [require_revised] refuses two cases that the old `SyncVerdict` kept
apart -- a page nobody saved, and a page that exists whose history we have not
fetched. From sync's point of view they are the same condition (no revision to
anchor on) and differ only in the remedy, which is what the message says.
"""


class UnresolvedPage(LookupError):
    """A title that cannot be resolved as asked, with the remedy in the text."""


@dataclass(frozen=True)
class ResolvedPage:
    """A title and whatever we hold for it. Nothing here refuses."""

    title: Title
    wiki_page: WikiPage | None
    head: Revision | None

    @property
    def exists(self) -> bool:
        """Does the wiki hold a page here. Row presence, not an inference."""
        return self.wiki_page is not None

    @property
    def pk(self) -> int:
        return self.title.pk

    @property
    def revid(self) -> int | None:
        """The head revid, or None when nothing is saved yet.

        A legitimate value rather than missing data: MediaWiki's ``baserevid``
        is optional and its absence means "create". Never infer intent from it
        -- record the intent explicitly (see ``PromotionIntent``).
        """
        return self.head.revid if self.head is not None else None

    @property
    def pageid(self) -> int | None:
        return self.wiki_page.pageid if self.wiki_page is not None else None


@dataclass(frozen=True)
class RevisedPage:
    """A title with a cached head revision. Every field is non-null."""

    title: Title
    head: Revision
    wiki_page: WikiPage | None
    """Present for anything fetched from a wiki. None only for a page we
    created locally and pushed but have not refetched -- the commit bridge --
    so callers that need ``pageid`` specifically must still say so."""

    @property
    def pk(self) -> int:
        return self.title.pk

    @property
    def revid(self) -> int:
        return self.head.revid


def resolve(session: Session, title: Title) -> ResolvedPage:
    """Everything we hold for one title, in one object."""
    wiki_page = session.get(WikiPage, title.pk) if title.pk is not None else None
    head = (
        session.get(Revision, wiki_page.latest_revision_pk)
        if wiki_page is not None
        else None
    )
    if head is None:
        head = _head_without_wiki_page(session, title)
    return ResolvedPage(title=title, wiki_page=wiki_page, head=head)


def resolve_many(session: Session, titles: list[Title]) -> dict[int, ResolvedPage]:
    """The batched form, for stat/listing paths that must stay at one query
    per concern rather than degrading to one per row."""
    pks = [t.pk for t in titles if t.pk is not None]
    if not pks:
        return {}

    wiki_pages = {
        wp.title_pk: wp
        for wp in session.exec(select(WikiPage).where(WikiPage.title_pk.in_(pks))).all()
    }
    revision_pks = [wp.latest_revision_pk for wp in wiki_pages.values()]
    heads = {
        rev.pk: rev
        for rev in (
            session.exec(select(Revision).where(Revision.pk.in_(revision_pks))).all()
            if revision_pks
            else []
        )
    }
    resolved: dict[int, ResolvedPage] = {}
    for title in titles:
        if title.pk is None:
            continue
        wiki_page = wiki_pages.get(title.pk)
        head = heads.get(wiki_page.latest_revision_pk) if wiki_page else None
        if head is None:
            head = _head_without_wiki_page(session, title)
        resolved[title.pk] = ResolvedPage(title=title, wiki_page=wiki_page, head=head)
    return resolved


def require_revised(session: Session, title: Title) -> RevisedPage:
    """A title with a head revision, or a refusal naming the remedy.

    This is the boundary. Sync and promotion take the result; they do not take
    a Title and check. A refusal here is the readable error the old null-check
    fan-out could not produce.
    """
    resolved = resolve(session, title)
    if resolved.head is None:
        if resolved.exists:
            raise UnresolvedPage(
                f"{title.title} exists on the wiki but no revision is cached: "
                "fetch it before comparing or pushing."
            )
        raise UnresolvedPage(
            f"{title.title} has no revision: nothing has been saved to the "
            "wiki at this title yet. Creating it is a push, not a comparison."
        )
    return RevisedPage(title=title, head=resolved.head, wiki_page=resolved.wiki_page)


def head_revision(session: Session, title: Title) -> Revision | None:
    """The head revision, or None when nothing is saved yet."""
    return resolve(session, title).head


def head_content(
    session: Session, title: Title, *, role: str = MAIN_SLOT
) -> Content | None:
    """The Content of one slot of the head revision.

    Takes an explicit ``session`` rather than being a property on ``Title``.
    This codebase deliberately works from detached snapshots -- the commit
    worker loads a page, rolls back, then does slow network I/O -- so a
    lazy-loading attribute would raise ``DetachedInstanceError`` exactly where
    it is least expected.
    """
    revision = head_revision(session, title)
    return None if revision is None else content_of_revision(session, revision, role)


def content_of_revision(
    session: Session, revision: Revision, role: str = MAIN_SLOT
) -> Content | None:
    slot = session.get(Slot, (revision.pk, role))
    return None if slot is None else session.get(Content, slot.content_pk)


def content_model_of(session: Session, title: Title) -> str | None:
    """The page's content model when it has one, else the namespace default.

    The two are deliberately reached through one function that says which it
    returned is *not* available: callers wanting to know the difference ask
    ``resolve(...).wiki_page`` directly. What matters is that a predicted model
    is never written back into a column that holds fetched ones.
    """
    wiki_page = session.get(WikiPage, title.pk) if title.pk is not None else None
    if wiki_page is not None:
        return wiki_page.content_model
    return default_content_model(session, title)


_ROLE_DEFAULT_MODEL: dict[NsRole, str] = {
    NsRole.page: "proofread-page",
    NsRole.index: "proofread-index",
}


def default_content_model(session: Session, title: Title) -> str:
    """The default content model for a save at this title.

    A *prediction* of what a save will produce, for the editor and for
    dispatch, derived from the namespace role rather than read off a page.
    Named so that no call site mistakes it for a fact about a page, and never
    written into ``WikiPage.content_model``, which holds fetched ones.

    Derived from the role, not from a stored per-namespace column, because
    that is what ProofreadPage itself guarantees: the ``Page``/``Index``
    namespaces hold those models by construction, whatever numeric ids a
    particular install gave them.
    """
    return _ROLE_DEFAULT_MODEL.get(title.namespace_role, "wikitext")


def _head_without_wiki_page(session: Session, title: Title) -> Revision | None:
    """The head of a title we hold revisions for but no WikiPage row.

    The commit bridge: we created the page by pushing, recorded the revision,
    and have not refetched the page identity yet. Ordinary, and temporary.
    """
    return session.exec(
        select(Revision)
        .where(Revision.title_pk == title.pk)
        .order_by(Revision.revid.desc())
        .limit(1)
    ).first()
