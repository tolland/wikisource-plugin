from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""The push queue: one reviewable page, replayed one revision at a time.

Deliberately **not** a status column on an audit log (discussion §12), and
deliberately **not** ``EditJournal`` + the commit worker (TODO §7). The journal
is the local per-save transaction log -- "the user typed this here" -- and
cross-site intent is a different claim with a different lifecycle: it is
proposed, reviewed, possibly abandoned, and only then written. Putting one in
the other is the overloading §12 identifies in ``Commit``.

Two tables because there are two lifetimes. A ``PromotionBatch`` is one page:
this correspondence and this direction, staged at this moment.
A ``Promotion`` is one ordered source revision inside it. Several pages do not
share an ordering constraint, approval decision, or conflict boundary, so they
do not share a batch.

**A promotion is built from a sync report and freezes what that report said.**
The report is recomputed on every load, and rightly: it describes revisions
currently held. But a queued push must not silently change meaning between
review and execution, so the base anchor and the source revision are copied in
at staging time and re-verified at push time. A row whose world moved under it
is a conflict, which is a state, not a surprise.
"""


class BatchStatus(str, Enum):
    """Where a run is in its life.

    ``partial`` is a first-class end state: an earlier revision may have been
    written before a later step conflicted or was refused. The page then holds
    part of the reviewed chain, which is neither complete nor a total failure.
    """

    draft = "draft"
    """Staged and editable. Rows can be added, dropped or re-staged."""

    running = "running"
    """At least one push has been attempted."""

    complete = "complete"
    """Every row reached ``pushed`` or ``skipped``."""

    partial = "partial"
    """Finished with some rows in ``conflict`` or ``error``."""

    aborted = "aborted"
    """Stopped by a person. Rows already pushed stay pushed -- there is no
    undo here; see the rollback item in the TODO."""


class PromotionStatus(str, Enum):
    staged = "staged"
    """Queued, not yet attempted."""

    pushed = "pushed"
    """Written to the target wiki. ``result_revid`` names the revision."""

    conflict = "conflict"
    """The target moved between staging and pushing, so the base no longer
    matches. Not an error: the correct outcome of a conditional write, and the
    fix is to re-stage against the new base."""

    error = "error"
    """The wiki refused it for some other reason. ``error_message`` says."""

    skipped = "skipped"
    """Dropped by a person before it ran."""


class PromotionIntent(str, Enum):
    """Recorded explicitly, never inferred from ``base_revid is None``.

    This is what lets the push set ``createonly``/``nocreate`` correctly. The
    inference is wrong in exactly the case that matters: a page we believe
    absent but which somebody created since would be silently overwritten by a
    create that was really an update.
    """

    create = "create"
    update = "update"


class PromotionBatch(SQLModel, table=True):
    """One page push: from a page the source wiki holds, to an address on the target.

    **Only what identifies the push, and what was reviewed.** Everything else
    is implied by the two ends and is resolved when needed rather than copied
    in here, where it could go stale or dangle:

    - the sites are the sites of the source page and the target title;
    - the page correspondence is ``find_pair`` of the two, and a stored pk to
      it could outlive an ``unpair``;
    - the tracked work and the page number come from the source's
      ``ProofreadPageMeta``;
    - the titles are the rows' own. A frozen title string was also a hazard:
      a page moved between staging and push would have been written to by its
      old name, which edits the redirect left behind and forks the content.

    What *is* frozen stays: ``source_head_revid`` and ``anchor_link_pk`` record
    what was reviewed, and ``Promotion.body`` what will be sent.
    """

    pk: int | None = Field(default=None, primary_key=True)

    source_page_pk: int = Field(foreign_key="page.pk", index=True)
    """A Page, not a Title: there is nothing to promote from a page the source
    wiki does not hold. That it also has a revision to push is checked when the
    batch is staged, which is where a refusal can say what to do about it."""

    target_title_pk: int = Field(foreign_key="title.pk", index=True)
    """A Title: the target is an address, and a create is the case where the
    wiki holds nothing there yet. Never null -- a title exists as soon as it
    can be named -- so a create and an update differ only in each promotion's
    recorded ``intent``, not in which columns of this row are filled."""

    source_head_revid: int | None = None
    anchor_link_pk: int | None = Field(
        default=None,
        foreign_key="revisionlink.pk",
        index=True,
        description="The correspondence this page's revision chain builds upon.",
    )
    label: str | None = None
    """A human's name for the run, for telling two of them apart in a list."""

    status: BatchStatus = Field(default=BatchStatus.draft, index=True)

    created_at: datetime = Field(default_factory=utcnow)


class Promotion(SQLModel, table=True):
    """One revision step of a batch: what is written, onto what, and what happened.

    The interesting fields are the two that pin the write down. ``base_revid``
    is the target revision this edit claims to follow -- sent as ``baserevid``
    so the wiki refuses the write if the page moved (discussion §8: revid, not
    timestamp, because two edits in the same second are indistinguishable by
    timestamp and that is exactly a bot's workload). ``pre_push_target_revid``
    is what the target was immediately before we wrote, which is what a
    rollback has to target and cannot be recomputed afterwards.
    """

    pk: int | None = Field(default=None, primary_key=True)
    batch_pk: int = Field(foreign_key="promotionbatch.pk", index=True)

    intent: PromotionIntent
    source_revision_pk: int = Field(foreign_key="revision.pk")
    predecessor_promotion_pk: int | None = Field(
        default=None,
        foreign_key="promotion.pk",
        index=True,
        description=(
            "The preceding revision step for this page. Its result revid is "
            "this edit's base; null for the first step."
        ),
    )
    base_revid: int | None = None
    """The target revid the first step claims to follow. Later steps derive
    their base from ``predecessor_promotion_pk.result_revid``; None for a
    create or a later step whose target revision does not exist yet."""

    body: str
    """The exact text that would be written, frozen at staging time.

    Stored rather than recomputed at push time so that what was reviewed is
    what is sent. A body that would be regenerated between the two is a body
    was not reviewed.
    """
    comment: str | None = None

    status: PromotionStatus = Field(default=PromotionStatus.staged, index=True)
    pre_push_target_revid: int | None = None
    """What the target's head was immediately before the write. Persisted
    because it is what a rollback targets, and it is unrecoverable once the
    push has appended a revision."""
    result_revid: int | None = None
    error_message: str | None = None

    staged_at: datetime = Field(default_factory=utcnow)
    pushed_at: datetime | None = None

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return (
            f"Promotion(pk={self.pk}, batch={self.batch_pk}, "
            f"{self.intent.value}, {self.status.value})"
        )
