from sqlalchemy import delete, or_, update
from sqlmodel import Session, col, select

from wtbot.model import (
    BoxRangeLink,
    Commit,
    Content,
    EditJournal,
    FetchRequest,
    FileBlob,
    IndexMeta,
    Page,
    PageLink,
    PromotionBatch,
    ProofreadPageMeta,
    Revision,
    RevisionLink,
    ScanAnnotation,
    Slot,
    TextTargetAnchor,
    Title,
)
from wtbot.model.fetch.fetch_request import FetchStatus

"""Deleting titles from the local cache, and everything keyed to them.

The cache-side counterpart of ``site_delete``: same schema (foreign keys on,
none with ON DELETE CASCADE), same reason for an explicit cascade, but scoped to
a set of title pks instead of a whole site. It removes *our* record of an
address -- the wiki is never touched -- so a title the wiki does hold comes back
the next time something fetches it. What it is for is the addresses that
should never have been recorded (a request for a non-canonical title leaves a
Title nothing can fetch), and clearing a stale cache entry.

Two kinds of reference are handled differently:

- Rows that exist only because of the title (revisions, journal, commits,
  annotations, metadata...) are deleted with it.
- Rows of a *survivor* that name the title (a page whose Index is being
  deleted, an Index whose scan is, a pairing or a staged promotion) cannot be
  deleted on the survivor's behalf and cannot be left dangling. [blockers]
  reports them and the caller refuses; deleting the set that includes the
  survivors, or removing the pairing first, is the way through.
"""


def _in(column, pks: list[int]):
    return col(column).in_(pks)


def blockers(session: Session, pks: list[int]) -> list[str]:
    """Why deleting exactly [pks] would strand a survivor, one line per cause.

    Empty means the delete can run. A pk in [pks] referencing another in
    [pks] is not a blocker -- both go."""
    doomed = set(pks)
    reasons: list[str] = []

    for meta in session.exec(
        select(ProofreadPageMeta).where(_in(ProofreadPageMeta.index_title_pk, pks))
    ).all():
        if meta.title_pk not in doomed:
            reasons.append(
                f"title {meta.title_pk} is paginated by index {meta.index_title_pk}"
            )
    for index in session.exec(
        select(IndexMeta).where(_in(IndexMeta.file_title_pk, pks))
    ).all():
        if index.title_pk not in doomed:
            reasons.append(
                f"index {index.title_pk} holds its scan at file {index.file_title_pk}"
            )
    for link in session.exec(
        select(PageLink).where(
            or_(_in(PageLink.local_page_pk, pks), _in(PageLink.remote_page_pk, pks))
        )
    ).all():
        if not {link.local_page_pk, link.remote_page_pk} <= doomed:
            reasons.append(f"page link {link.pk} pairs it with another title")
    for batch in session.exec(
        select(PromotionBatch).where(
            or_(
                _in(PromotionBatch.source_page_pk, pks),
                _in(PromotionBatch.target_title_pk, pks),
            )
        )
    ).all():
        reasons.append(f"promotion batch {batch.pk} stages it")
    return reasons


def delete_titles(session: Session, pks: list[int]) -> None:
    """Delete the titles [pks] and what hangs off them. Commits: half a
    cascade is worse than none. Callers check [blockers] first; an unchecked
    survivor reference fails here on the foreign key, rolling everything back.

    Queued fetches for the titles are cancelled rather than deleted -- they
    reference no title row, only its name, and would otherwise re-create what
    was just removed.
    """
    if not pks:
        return

    revisions = select(Revision.pk).where(_in(Revision.page_pk, pks))
    # Pinned before the slots go: the orphan test consults them.
    slot_contents = set(
        session.exec(select(Slot.content_pk).where(Slot.revision_pk.in_(revisions)))
    )
    shared = set(
        session.exec(
            select(Slot.content_pk).where(
                col(Slot.content_pk).in_(slot_contents),
                col(Slot.revision_pk).not_in(revisions),
            )
        )
    )
    orphaned = list(slot_contents - shared)

    titles = session.exec(select(Title).where(_in(Title.pk, pks))).all()
    for site_pk, name in {(t.site_pk, t.title) for t in titles}:
        session.execute(
            update(FetchRequest)
            .where(
                FetchRequest.site_pk == site_pk,
                FetchRequest.title == name,
                col(FetchRequest.status).in_(
                    [FetchStatus.pending, FetchStatus.in_progress]
                ),
            )
            .values(status=FetchStatus.cancelled)
        )

    for model, clause in [
        (
            RevisionLink,
            or_(
                col(RevisionLink.local_revision_pk).in_(revisions),
                col(RevisionLink.remote_revision_pk).in_(revisions),
            ),
        ),
        (Slot, col(Slot.revision_pk).in_(revisions)),
        (Content, _in(Content.pk, orphaned)),
        (Revision, _in(Revision.page_pk, pks)),
        (ProofreadPageMeta, _in(ProofreadPageMeta.title_pk, pks)),
        (IndexMeta, _in(IndexMeta.title_pk, pks)),
        (FileBlob, _in(FileBlob.page_pk, pks)),
        (ScanAnnotation, _in(ScanAnnotation.title_pk, pks)),
        (BoxRangeLink, _in(BoxRangeLink.title_pk, pks)),
        (TextTargetAnchor, _in(TextTargetAnchor.title_pk, pks)),
        (EditJournal, _in(EditJournal.title_pk, pks)),
        (Commit, _in(Commit.title_pk, pks)),
        (Page, _in(Page.pk, pks)),
        (Title, _in(Title.pk, pks)),
    ]:
        session.execute(delete(model).where(clause))
    session.commit()
