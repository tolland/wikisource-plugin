from pydantic import BaseModel
from sqlalchemy import delete, or_, update
from sqlmodel import Session, func, select

from wtbot.model import (
    BoxRangeLink,
    Commit,
    Content,
    EditJournal,
    FetchRequest,
    FileBlob,
    FileMeta,
    IndexMeta,
    Namespace,
    Page,
    ProofreadPageMeta,
    Revision,
    RevisionLink,
    ScanAnnotation,
    Site,
    SiteCredential,
    Slot,
    TextTargetAnchor,
    Transclusion,
)

"""Deleting a site, and everything that only exists because of it.

The schema declares its foreign keys and every connection runs with
``PRAGMA foreign_keys=ON``, but none of the keys carry ON DELETE CASCADE --
deliberately, because "delete a wiki and its whole local cache" should be an
explicit, previewable operation, not a side effect a stray DELETE can trigger.
So the cascade lives here, in one place, in dependency order.

The plan is computed with the same predicates the deletion uses; the CLI shows
it *instead of* deleting unless --force is given, which is why there is no
separate dry-run flag.

Two rows survive on purpose:

- ``Content`` rows still referenced by another site's slots. The body store is
  content-addressed and shared across sites when bytes match; only rows this
  deletion would orphan are removed.
- ``OcrBackendConfig`` rows. Their ``scope`` string is not a foreign key
  precisely so a config outlives the Site it was named after (see the model's
  docstring).

``FileMeta.source_page_pk`` may point at this site's pages from a *surviving*
row (in principle, a crop whose provenance crosses sites); those links are
cleared rather than taking the row with them.
"""


class TableRows(BaseModel):
    """How many rows one table loses. A typed pair rather than a dict entry so
    the API response and the CLI rendering share a shape."""

    table: str
    rows: int


class SiteDeletePlan(BaseModel):
    """What deleting one site removes, stated before (and returned after)."""

    site_pk: int
    label: str | None
    family: str
    code: str
    counts: list[TableRows]  # non-empty tables only, cascade order

    @property
    def total_rows(self) -> int:
        return sum(entry.rows for entry in self.counts)


def _page_pks(site_pk: int):
    return select(Page.pk).where(Page.site_pk == site_pk)


def _revision_pks(site_pk: int):
    return select(Revision.pk).where(Revision.page_pk.in_(_page_pks(site_pk)))


def _orphaned_content_pks(site_pk: int):
    """Content referenced by this site's slots and by nobody else's."""
    revisions = _revision_pks(site_pk)
    referenced_here = select(Slot.content_pk).where(Slot.revision_pk.in_(revisions))
    referenced_elsewhere = select(Slot.content_pk).where(
        Slot.revision_pk.not_in(revisions)
    )
    return select(Content.pk).where(
        Content.pk.in_(referenced_here), Content.pk.not_in(referenced_elsewhere)
    )


def _predicates(site_pk: int) -> list[tuple[type, object]]:
    """(model, where-clause) per table, in the order deletion must run.

    One list drives both the plan and the deletion so they cannot disagree
    about what "everything belonging to this site" means.
    """
    pages = _page_pks(site_pk)
    revisions = _revision_pks(site_pk)
    return [
        (
            RevisionLink,
            or_(
                RevisionLink.local_revision_pk.in_(revisions),
                RevisionLink.remote_revision_pk.in_(revisions),
            ),
        ),
        (Slot, Slot.revision_pk.in_(revisions)),
        (Content, Content.pk.in_(_orphaned_content_pks(site_pk))),
        (Revision, Revision.page_pk.in_(pages)),
        (ProofreadPageMeta, ProofreadPageMeta.page_pk.in_(pages)),
        (IndexMeta, or_(IndexMeta.site_pk == site_pk, IndexMeta.page_pk.in_(pages))),
        (FileMeta, FileMeta.page_pk.in_(pages)),
        (FileBlob, FileBlob.page_pk.in_(pages)),
        (ScanAnnotation, ScanAnnotation.page_pk.in_(pages)),
        (BoxRangeLink, BoxRangeLink.page_pk.in_(pages)),
        (TextTargetAnchor, TextTargetAnchor.page_pk.in_(pages)),
        (EditJournal, EditJournal.page_pk.in_(pages)),
        (Commit, Commit.page_pk.in_(pages)),
        (
            Transclusion,
            or_(
                Transclusion.site_pk == site_pk,
                Transclusion.source_page_pk.in_(pages),
            ),
        ),
        (FetchRequest, FetchRequest.site_pk == site_pk),
        (Page, Page.site_pk == site_pk),
        (Namespace, Namespace.site_pk == site_pk),
        (SiteCredential, SiteCredential.site_pk == site_pk),
        (Site, Site.pk == site_pk),
    ]


def plan_site_delete(session: Session, site: Site) -> SiteDeletePlan:
    """Count what deleting ``site`` would remove, touching nothing."""
    assert site.pk is not None
    counts = [
        TableRows(table=model.__tablename__, rows=rows)
        for model, clause in _predicates(site.pk)
        if (
            rows := session.exec(
                select(func.count()).select_from(model).where(clause)
            ).one()
        )
    ]
    return SiteDeletePlan(
        site_pk=site.pk,
        label=site.label,
        family=site.family,
        code=site.code,
        counts=counts,
    )


def execute_site_delete(session: Session, site: Site) -> SiteDeletePlan:
    """Delete ``site`` and its dependents. Returns what was deleted (the plan,
    counted before the rows went). Commits: half a cascade is worse than none.
    """
    assert site.pk is not None
    plan = plan_site_delete(session, site)
    pages = _page_pks(site.pk)

    # The orphan predicate is self-referential through `slot`, so the pks must
    # be pinned down before the slot rows it consults are gone.
    orphaned_contents = list(session.exec(_orphaned_content_pks(site.pk)).all())

    # Surviving FileMeta rows may cite this site's pages as crop provenance;
    # FetchRequest children cite their parent within the doomed set. Both
    # references must be cleared before the rows behind them go, or the
    # foreign keys (rightly) refuse.
    session.execute(
        update(FileMeta)
        .where(FileMeta.source_page_pk.in_(pages), FileMeta.page_pk.not_in(pages))
        .values(source_page_pk=None)
    )
    session.execute(
        update(FetchRequest)
        .where(FetchRequest.site_pk == site.pk)
        .values(parent_pk=None)
    )

    for model, clause in _predicates(site.pk):
        if model is Content:
            clause = Content.pk.in_(orphaned_contents)
        session.execute(delete(model).where(clause))
    session.commit()
    return plan
