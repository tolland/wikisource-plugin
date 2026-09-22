from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlmodel import Session, select

from wtbot.model import Namespace, NsRole, Site, Title
from wtbot.timeutil import as_utc
from wtbot.wiki.client import WikiClient
from wtbot.wiki.wiki_types import RemoteChange

"""Planning a refresh: which titles to refetch, and when not to guess.

Refetching 400 pages to find the two that moved is slow and rude to the wiki.
``list=recentchanges`` answers "what moved since X" in one or two requests, and
the titles it returns are fed to the ordinary fetch path -- there is no second
fetch mechanism, only a smaller list.

Three things this must not get wrong:

- **The recentchanges table is pruned.** ``$wgRCMaxAge`` defaults to 90 days.
  Past that horizon "nothing changed" and "the wiki no longer remembers" are the
  same empty response, and trusting it would silently skip every page that moved
  while we were away. So the horizon is *asked for*, and a since timestamp older than
  it downgrades the plan to a full refresh rather than a confident wrong answer.
- **A changed revid is not a changed page.** Null and touch edits create
  revisions with identical content -- four of them in the Canadian patent
  fixture. This produces candidates, never verdicts; divergence is decided by
  content comparison after fetching.
- **Namespace ids are per-site.** ``Title``/``Index`` are 104/106 on
  en.wikisource and different on a fresh ProofreadPage install, so the
  server-side filter is resolved from this site's Namespace rows by *role*.

Moves and deletions are out of scope here and deliberately not half-covered:
they are ``log`` entries needing ``list=logevents`` to read properly, and
discussion section 5 wants them classified, not merely noticed.
"""

# Only ever narrows a scan we would otherwise do in full, so erring large is
# free; erring small silently drops changes.
DEFAULT_WATCHED_ROLES = (NsRole.page, NsRole.index)


class RefreshBasis(str, Enum):
    """How the plan was arrived at -- part of the result, not a log line.

    A caller that cannot tell an incremental plan from a full one cannot tell
    "two pages moved" from "we gave up and listed everything".
    """

    incremental = "incremental"
    """recentchanges answered, and the supplied since timestamp was inside its horizon."""

    full = "full"
    """The supplied since timestamp is older than the wiki still remembers. Every
    known title is a candidate."""


@dataclass(frozen=True)
class RefreshPlan:
    """What to refetch, and how much to believe it."""

    basis: RefreshBasis
    titles: tuple[str, ...] = ()
    reason: str | None = None
    """Why the basis is what it is, when it is not the happy path."""

    changes: tuple[RemoteChange, ...] = field(default=())
    """The raw entries behind ``titles``, for reporting. Several changes can
    collapse to one title; the fetch list is deduplicated, this is not."""


def plan_refresh(
    session: Session,
    site: Site,
    client: WikiClient,
    *,
    since: datetime,
    title_prefix: str | None = None,
    roles: tuple[NsRole, ...] = DEFAULT_WATCHED_ROLES,
) -> RefreshPlan:
    """Decide which of this site's known titles are worth refetching.

    ``since`` is supplied by the caller on every request. ``title_prefix`` narrows
    to one work (``Page:Foo.djvu/``): recentchanges has no prefix filter --
    ``rctitle`` takes a single page -- so this is applied here, over metadata
    we already paid for rather than a fetch per candidate.
    """
    # CLI dates without an explicit timezone are interpreted as UTC.
    since = as_utc(since)
    if since is None:
        raise ValueError("since is required")

    horizon = as_utc(client.oldest_retained_change())
    if horizon is not None and since < horizon:
        return _full(
            session,
            site,
            title_prefix,
            f"since {since.isoformat()} predates the oldest change the wiki "
            f"still holds ({horizon.isoformat()}); recentchanges cannot answer",
        )

    changes = client.recent_changes(
        since=since,
        namespace_keys=_namespace_keys(session, site, roles),
    )

    known = _known_titles(session, site, title_prefix)
    titles: list[str] = []
    seen: set[str] = set()
    for change in changes:
        if title_prefix and not change.title.startswith(title_prefix):
            continue
        # A title we do not hold is a *creation* within the work -- which is
        # exactly what a partially transcribed index grows -- so a prefix scan
        # takes it even though nothing local matches yet. Without a prefix
        # there is no way to tell "new page of a work we track" from "some
        # other page on the wiki", so only known titles qualify.
        if not title_prefix and change.title not in known:
            continue
        if change.title not in seen:
            seen.add(change.title)
            titles.append(change.title)

    return RefreshPlan(
        basis=RefreshBasis.incremental,
        titles=tuple(titles),
        changes=tuple(changes),
    )


def _full(
    session: Session, site: Site, title_prefix: str | None, reason: str
) -> RefreshPlan:
    return RefreshPlan(
        basis=RefreshBasis.full,
        titles=tuple(sorted(_known_titles(session, site, title_prefix))),
        reason=reason,
    )


def _known_titles(session: Session, site: Site, title_prefix: str | None) -> set[str]:
    statement = select(Title.title).where(Title.site_pk == site.pk)
    if title_prefix:
        statement = statement.where(Title.title.startswith(title_prefix))
    return set(session.exec(statement).all())


def _namespace_keys(
    session: Session, site: Site, roles: tuple[NsRole, ...]
) -> list[int] | None:
    """This site's numeric ids for the watched roles, or None to not filter.

    None rather than an empty list when nothing resolves: an empty
    ``rcnamespace`` would be a filter matching nothing, and a namespace table
    that has not been synced yet must not look like a wiki where nothing ever
    changes.
    """
    keys = session.exec(
        select(Namespace.key).where(
            Namespace.site_pk == site.pk,
            Namespace.role.in_(roles),
        )
    ).all()
    return sorted(keys) or None
