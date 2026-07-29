from sqlmodel import Session, select

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
us; see docs/proofread-page-sha1-discordance.md for why it cannot replace ours.
"""


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
        return existing

    content = Content(
        content_sha1=digest,
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
    revision.remote_sha1 = normalize_sha1(remote.sha1)
    revision.remote_size = remote.size
    session.add(revision)
    session.flush()

    _upsert_slot(session, revision, content, role=MAIN_SLOT)

    page.latest_revision_pk = revision.pk
    session.add(page)
    return revision


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
