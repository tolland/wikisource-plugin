from sqlmodel import Session, select

from wtbot.content_model import comparable_sha1
from wtbot.model import MAIN_SLOT, Content, Page, Revision, Slot
from wtbot.wiki.sha1 import content_sha1_base36, normalize_sha1
from wtbot.wiki.wiki_types import RemotePage

"""Writing fetched revisions into the page -> revision -> slot -> content chain.

Owned by the fetch worker. The commit worker never writes here: a push records
its outcome on ``Commit`` and enqueues a refetch, and the refetch is what makes
the revision concrete. That keeps one writer per table and makes the reconcile
step ("did the wiki serve back what we submitted?") a comparison between two
tables rather than a trust decision.

Content is addressed by *our* hash of the bytes the API served, so identical
text -- across revisions, and across sites -- collapses to one row. The wiki's
own hash rides along as ``remote_sha1`` for the cases where it can corroborate
us; see docs/reference/proofread-page-sha1-discordance.md for why it cannot replace ours.
"""


class RemoteIdentityError(ValueError):
    """The registered site no longer has the identity the cache recorded.

    MediaWiki's page and revision ids are stable only for the lifetime of one
    wiki database. Reusing a wtbot cache after restoring/replacing that
    database must stop at the first contradiction instead of combining two
    unrelated histories under one Site row.
    """


def validate_remote_identity(session: Session, page: Page, remote: RemotePage) -> None:
    """Refuse a remote snapshot that contradicts this Site's cached identity."""
    if remote.pageid is not None:
        if page.pageid is not None and page.pageid != remote.pageid:
            raise RemoteIdentityError(
                f"site {page.site_pk} title {page.title!r} changed pageid "
                f"from {page.pageid} to {remote.pageid}; the MediaWiki database "
                "may have been restored or replaced"
            )

        other_page = session.exec(
            select(Page).where(
                Page.site_pk == page.site_pk,
                Page.pageid == remote.pageid,
                Page.pk != page.pk,
            )
        ).first()
        if other_page is not None:
            raise RemoteIdentityError(
                f"site {page.site_pk} pageid {remote.pageid} is already cached as "
                f"{other_page.title!r}, not {page.title!r}; the MediaWiki database "
                "may have been restored or a move needs reconciling"
            )

    if remote.revid is None:
        return

    # Cross-page identity requires a complete page snapshot. Production fetches
    # always carry pageid (see PywikibotClient.get_page/get_history), while
    # small FakeWikiClient fixtures commonly omit it and use placeholder revids.
    # Treating those partial snapshots as authoritative site-global identity
    # records makes unrelated unit tests fail without improving the production
    # guard. Same-page revision immutability below remains enforceable from a
    # revid alone.
    if remote.pageid is not None:
        other_revision = session.exec(
            select(Revision)
            .join(Page, Page.pk == Revision.page_pk)
            .where(
                Page.site_pk == page.site_pk,
                Revision.revid == remote.revid,
                Revision.page_pk != page.pk,
            )
        ).first()
        if other_revision is not None:
            other_revision_page = session.get(Page, other_revision.page_pk)
            other_title = (
                other_revision_page.title if other_revision_page else "unknown"
            )
            raise RemoteIdentityError(
                f"site {page.site_pk} revid {remote.revid} is already cached for "
                f"{other_title!r}, not {page.title!r}; the MediaWiki database may "
                "have been restored or replaced"
            )

    existing = session.exec(
        select(Revision).where(
            Revision.page_pk == page.pk,
            Revision.revid == remote.revid,
        )
    ).first()
    if existing is None or existing.pk is None:
        return
    slot = session.get(Slot, (existing.pk, MAIN_SLOT))
    content = None if slot is None else session.get(Content, slot.content_pk)
    digest = content_sha1_base36(remote.text)
    if content is not None and (
        content.content_sha1 != digest or content.content_model != remote.content_model
    ):
        raise RemoteIdentityError(
            f"site {page.site_pk} revid {remote.revid} for {page.title!r} "
            "changed content; revision ids are immutable, so the MediaWiki "
            "database may have been restored or replaced"
        )


def head_revision(session: Session, page: Page) -> Revision | None:
    """The page's current revision, or None for a placeholder."""
    if page.latest_revision_pk is None:
        return None
    return session.get(Revision, page.latest_revision_pk)


def head_content(
    session: Session, page: Page, *, role: str = MAIN_SLOT
) -> Content | None:
    """The Content of one slot of the page's current revision.

    Takes an explicit ``session`` rather than being a property on ``Page``.
    This codebase deliberately works from detached snapshots -- the commit
    worker loads a page, rolls back, then does slow network I/O -- so a
    lazy-loading attribute would raise ``DetachedInstanceError`` exactly where
    it is least expected. Requiring the session makes the database access
    visible at the call site.
    """
    revision = head_revision(session, page)
    if revision is None:
        return None
    slot = session.get(Slot, (revision.pk, role))
    return None if slot is None else session.get(Content, slot.content_pk)


def upsert_content(
    session: Session,
    text: str,
    *,
    content_model: str | None,
    remote_sha1: str | None = None,
    remote_size: int | None = None,
) -> Content:
    """Return the Content row for ``text``, creating it if new.

    Deduplicates on (our hash, content model). A row already present may have
    been written from another site entirely -- that sharing is the point.
    """
    digest = content_sha1_base36(text)
    existing = session.exec(
        select(Content).where(
            Content.content_sha1 == digest,
            Content.content_model == content_model,
        )
    ).first()
    if existing is not None:
        # Fill in the wiki's own values if this is the first time we have seen
        # them for content we already held from elsewhere.
        if existing.remote_sha1 is None and remote_sha1 is not None:
            existing.remote_sha1 = normalize_sha1(remote_sha1)
            existing.remote_size = remote_size
            session.add(existing)
        # A row predating the column, or one written by an older wtbot. Filled
        # in on the way past rather than left for the migration to be the only
        # thing that ever computes it.
        if existing.comparable_sha1 is None:
            existing.comparable_sha1 = comparable_sha1(text, content_model)
            session.add(existing)
        return existing

    content = Content(
        content_sha1=digest,
        comparable_sha1=comparable_sha1(text, content_model),
        content_model=content_model,
        text=text,
        size=len(text.encode("utf-8")),
        remote_sha1=normalize_sha1(remote_sha1),
        remote_size=remote_size,
    )
    session.add(content)
    session.flush()
    return content


def record_head_revision(
    session: Session, page: Page, remote: RemotePage
) -> Revision | None:
    """Record the revision a fetch just observed, and point the page at it.

    Only the head is recorded: a fetch sees one revision, and the store is
    deliberately sparse -- ``Page.history_complete_from_revid`` stays None
    because nothing here establishes a contiguous range. A later history walk
    is what fills gaps in and sets that marker.

    Returns None for a page with no remote revision (a placeholder), which must
    not manufacture a revision row.
    """
    if remote.revid is None or page.pk is None:
        return None

    validate_remote_identity(session, page, remote)

    content = upsert_content(
        session,
        remote.text,
        content_model=remote.content_model,
        remote_sha1=remote.sha1,
        remote_size=remote.size,
    )

    revision = session.exec(
        select(Revision).where(
            Revision.page_pk == page.pk, Revision.revid == remote.revid
        )
    ).first()
    if revision is None:
        revision = Revision(page_pk=page.pk, revid=remote.revid)

    revision.parent_revid = remote.parentid
    revision.timestamp = remote.timestamp
    revision.contributor = remote.user
    revision.comment = remote.comment
    session.add(revision)
    session.flush()

    _upsert_slot(session, revision, content, role=MAIN_SLOT)

    page.latest_revision_pk = revision.pk
    session.add(page)
    # A head whose parent we do not hold marks nothing; a head with *no* parent
    # is the page's only revision, and that is a complete history worth
    # recording -- otherwise every never-edited page reads as "we did not look
    # far enough" when there is nowhere further to look.
    _mark_contiguous_history(session, page)
    return revision


def record_history(
    session: Session, page: Page, remotes: list[RemotePage]
) -> list[Revision]:
    """Record older revisions of a page without moving the head.

    The head denormalisation on ``Page`` is owned by ``record_head_revision``;
    this fills in behind it, so a caller can walk a page's history without the
    walk deciding what "current" means.

    Sets ``Page.history_complete_from_revid`` to the oldest revid stored *only
    when the run reaches back from the head contiguously*: without that, a
    later base search cannot tell "the histories diverge here" from "this is
    merely the oldest revision we happened to fetch", which is the whole reason
    the marker exists.
    """
    if page.pk is None:
        return []

    stored: list[Revision] = []
    for remote in remotes:
        if remote.revid is None:
            continue
        validate_remote_identity(session, page, remote)
        content = upsert_content(
            session,
            remote.text,
            content_model=remote.content_model,
            remote_sha1=remote.sha1,
            remote_size=remote.size,
        )
        revision = session.exec(
            select(Revision).where(
                Revision.page_pk == page.pk, Revision.revid == remote.revid
            )
        ).first()
        if revision is None:
            revision = Revision(page_pk=page.pk, revid=remote.revid)
        revision.parent_revid = remote.parentid
        revision.timestamp = remote.timestamp
        revision.contributor = remote.user
        revision.comment = remote.comment
        session.add(revision)
        session.flush()
        _upsert_slot(session, revision, content, role=MAIN_SLOT)
        stored.append(revision)

    _mark_contiguous_history(session, page)
    return stored


def _mark_contiguous_history(session: Session, page: Page) -> None:
    """Walk parent_revid back from the head and record how far we can get.

    Following ``parent_revid`` rather than sorting by revid: consecutive revids
    are not a guarantee of adjacency (another page's edit takes one in
    between), and the parent pointer is what MediaWiki itself means by "the
    revision before this one".
    """
    head = head_revision(session, page)
    if head is None:
        return

    by_revid = {
        revision.revid: revision
        for revision in session.exec(
            select(Revision).where(Revision.page_pk == page.pk)
        ).all()
    }
    current = head
    while current.parent_revid is not None:
        parent = by_revid.get(current.parent_revid)
        if parent is None:
            break
        current = parent

    # parent_revid of None means the page's first revision -- the range is then
    # complete to the beginning, which is still just "from this revid onwards".
    page.history_complete_from_revid = current.revid
    session.add(page)


def _upsert_slot(
    session: Session, revision: Revision, content: Content, *, role: str
) -> Slot:
    slot = session.get(Slot, (revision.pk, role))
    if slot is None:
        slot = Slot(revision_pk=revision.pk, role=role)
    slot.content_pk = content.pk
    # We only ever see the head here, so we cannot tell an inherited slot from a
    # changed one; a history walk that fetches consecutive revisions can set
    # this properly. Left None rather than guessed.
    session.add(slot)
    return slot
