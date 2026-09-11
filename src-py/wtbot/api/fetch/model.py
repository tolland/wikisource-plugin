from datetime import datetime

from pydantic import BaseModel, Field

from wtbot.fetch.queue_runner import (
    DEFAULT_BATCH,
    DEFAULT_MAX_PASSES,
    DrainStop,
)
from wtbot.incremental import RefreshBasis
from wtbot.model import FetchKind, FetchStatus


class RefreshCreate(BaseModel):
    """What to refresh. Field descriptions are ``Field(description=...)`` rather
    than attribute docstrings so they reach the OpenAPI schema -- Pydantic
    ignores the docstring form unless ``use_attribute_docstrings`` is set, and a
    body that renders as an undocumented JSON blob is the thing this fixes."""

    label: str = Field(description="The registered site to refresh (see POST /sites).")
    since: datetime | None = Field(
        default=None,
        description=(
            "Overrides the site's stored watermark. Mostly for re-running a "
            "window that has already been consumed."
        ),
    )
    title_prefix: str | None = Field(
        default=None,
        description=(
            "Narrow to one work, e.g. 'Page:Foo.djvu/'. recentchanges has no "
            "prefix filter -- rctitle takes a single page -- so this is applied "
            "to the returned metadata. With a prefix, titles not held locally "
            "are taken too, which is how a partially transcribed index grows."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="Plan only: report what would be refetched, advance nothing.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "label": "en.wikisource",
                    "title_prefix": "Page:Canadian patent 29537.djvu/",
                    "dry_run": True,
                }
            ]
        }
    }


class RefreshPlanOut(BaseModel):
    """The plan, as reported. ``basis`` is the load-bearing field: a caller that
    cannot tell an incremental plan from a full one cannot tell "two pages
    moved" from "we could not tell, so here is everything"."""

    basis: RefreshBasis = Field(
        description="'incremental' if recentchanges answered; 'full' otherwise."
    )
    reason: str | None = Field(
        default=None,
        description="Why the basis is not incremental, when it is not.",
    )
    titles: list[str] = Field(description="Titles to refetch, deduplicated.")
    watermark: datetime | None = Field(
        default=None,
        description=(
            "Newest change timestamp observed. None on a full plan, which read "
            "no change stream and so may claim no position in one."
        ),
    )
    changes: int = Field(
        description="Raw recentchanges entries behind `titles`; several can "
        "collapse to one title."
    )


class RefreshResult(BaseModel):
    plan: RefreshPlanOut
    enqueued: int = Field(description="FetchRequests created; 0 for a dry run.")
    watermark: datetime | None = Field(
        default=None,
        description="The site's watermark after the run.",
    )


class FetchCreate(BaseModel):
    title: str
    label: str = Field(
        description=(
            "The registered site to fetch from. A site is never created here: "
            "an unknown label is a 404, because inventing one would fetch from "
            "a wiki nobody configured, with no credentials."
        )
    )
    kind: FetchKind = FetchKind.single
    depth: int = 0
    revisions: int = Field(
        default=1,
        ge=1,
        description=(
            "Revisions to store, counting back from the head. 1 is a normal "
            "fetch; more fills in history for the cross-site anchor search, "
            "which cannot find a match at the head when one side was imported "
            "from an older revision of the other."
        ),
    )


class DrainRequest(BaseModel):
    """How much of the queue to work through in this call."""

    batch: int = Field(
        default=DEFAULT_BATCH, ge=1, description="Requests claimed per pass."
    )
    max_passes: int = Field(
        default=DEFAULT_MAX_PASSES,
        ge=1,
        description=(
            "Safety bound on passes. Several are normal -- a fan-out enqueues "
            "children mid-drain -- so this only stops a pathological cycle."
        ),
    )


class DrainResponse(BaseModel):
    handled: int = Field(description="Fetch requests processed in this call.")
    passes: int = Field(description="Claim/process cycles it took.")
    remaining: int = Field(
        description="Requests still pending or in progress afterwards."
    )
    stop_reason: DrainStop = Field(
        description=(
            "'queue_empty' when the queue ran out; 'max_passes' when the bound "
            "was hit first; 'rate_limited' when the wiki refused us. The last "
            "two leave work queued."
        )
    )
    complete: bool = Field(description="Queue empty and nothing left behind.")
    retry_after: float | None = Field(
        default=None,
        description=(
            "Seconds the wiki asked us to wait, when it said so. Reported "
            "rather than slept through -- draining again straight away is how "
            "a rate limit becomes a worse rate limit."
        ),
    )


class QueueStatsResponse(BaseModel):
    """What is in the queue, without draining it."""

    counts: dict[FetchStatus, int] = Field(description="Requests by status.")
    pending: int = Field(description="Requests a drain would pick up now.")
    total: int = Field(description="All requests ever recorded, by status.")
    oldest_pending_at: datetime | None = Field(
        default=None, description="When the oldest pending request was queued."
    )
