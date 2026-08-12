from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""The push queue: reviewable, cancellable intent, one row per page.

Deliberately **not** a status column on an audit log (discussion §12), and
deliberately **not** ``EditJournal`` + the commit worker (TODO §7). The journal
is the local per-save transaction log -- "the user typed this here" -- and
cross-site intent is a different claim with a different lifecycle: it is
proposed, reviewed, possibly abandoned, and only then written. Putting one in
the other is the overloading §12 identifies in ``Commit``.

Two tables because there are two lifetimes. A ``PromotionBatch`` is a run: this
work, this direction, approved by this person, at this moment. A ``Promotion``
is one page inside it, with its own outcome -- a batch that half-succeeds is
the normal case, not an error state, and each row has to say which half it was
in.

**A promotion is built from a sync report and freezes what that report said.**
The report is recomputed on every load, and rightly: it describes revisions
currently held. But a queued push must not silently change meaning between
review and execution, so the base anchor and the source revision are copied in
at staging time and re-verified at push time. A row whose world moved under it
is a conflict, which is a state, not a surprise.
"""


class BatchStatus(str, Enum):
    """Where a run is in its life.

    ``partial`` is a first-class end state, not a failure: pushing 300 pages
    through a rate-limited wiki and having 12 refused is Tuesday, and a status
    that could not say so would force the whole run to read as broken.
    """

    draft = "draft"
    """Staged and editable. Rows can be added, dropped or re-staged."""

    approved = "approved"
    """A person has signed off. Frozen: re-staging means a new batch."""

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
    """One push run: a work, a direction, and an approval."""

    pk: int | None = Field(default=None, primary_key=True)

    source_site_pk: int = Field(foreign_key="site.pk", index=True)
    target_site_pk: int = Field(foreign_key="site.pk", index=True)
    index_link_pk: int | None = Field(
        default=None,
        foreign_key="indexlink.pk",
        index=True,
        description="The tracked work, when the pair is tracked.",
    )

    source_index_title: str
    target_index_title: str
    label: str | None = None
    """A human's name for the run, for telling two of them apart in a list."""

    status: BatchStatus = Field(default=BatchStatus.draft, index=True)

    approved_by: str | None = None
    approved_at: datetime | None = None
    """Who signed this off, and when. Null while it is a draft -- and a batch
    cannot run without them, which is the point of storing them here rather
    than trusting the caller to have asked."""

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

    page_link_pk: int | None = Field(
        default=None, foreign_key="pagelink.pk", index=True
    )
    """The pairing this promotion acts within. Null for a create, which has no
    target page to have been paired with yet."""

    source_page_pk: int = Field(foreign_key="page.pk", index=True)
    target_page_pk: int | None = Field(default=None, foreign_key="page.pk", index=True)
    target_title: str
    """Held as text as well as a pk: a create has no target row to point at,
    and the title is what the write is addressed to either way."""

    page_number: int | None = None

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
    anchor_link_pk: int | None = Field(
        default=None,
        foreign_key="remotelink.pk",
        index=True,
        description=(
            "The asserted correspondence this push replays on top of. Null "
            "only for a create, which has nothing to replay onto -- a staged "
            "update without one is the bug this column exists to make visible."
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
    nobody approved.
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
            f"{self.intent.value} {self.target_title!r}, {self.status.value})"
        )
