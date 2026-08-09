from dataclasses import dataclass, field
from enum import Enum

from sqlmodel import Session, select

from wtbot.index_link_store import find_index_link
from wtbot.matching import (
    MatchOutcome,
    compare_pages,
    find_anchor,
    index_children,
)
from wtbot.model import FetchState, FileBlob, NsRole, Page, PageLink, Site
from wtbot.page_link_store import find_pair
from wtbot.remote_link_store import ladder
from wtbot.revision_store import head_revision
from wtbot.vfs.store import canonical_title

"""``sync --from Index:X [--to Index:Y]``: what it would take to make the target
match the source. A report, and only a report.

**Directional, unlike everything under it.** A ``PageLink`` is an unordered
claim that two pages are the same page, and a ``RemoteLink`` an unordered claim
that two revisions hold the same content -- neither side is privileged, because
"A corresponds to B" and "B corresponds to A" are the same fact. A sync is the
opposite: it asks what would be *written*, to *which* wiki, and reversing it
reverses the answer. So this module has a source and a target where the link
layer has a local and a remote, and it reads the unordered facts underneath in
whichever orientation they were stored.

**The work need not exist on the target.** That is the motivating case (TODO
§7: a work present on en.wikisource and absent locally), and it is the reason
this cannot be keyed on a tracked work -- there is no pairing to key on until
the target index exists. So the report is addressed by title, and reports the
absent side as work to do rather than as an error.

Three kinds of absence, and they are not the same:

- the target ``Index:`` does not exist -- the whole work is a create;
- a target ``Page:`` has no row -- that page is a create;
- a target ``Page:`` has a row with no revision. This is a **placeholder**, the
  stub an index fan-out writes for a page ProofreadPage paginates but nobody has
  transcribed (``pageid``/``revid`` None, ``fetch_status=done`` meaning "we
  know: absent"). It is still a create, and distinguishing it from "not fetched
  yet" is the difference between work to do and a gap in what we know.

**The scan check runs first** (discussion §6). If the two sides' backing scans
are different uploads then local page 101 is not target page 101, and every
verdict below it is off by an unknown offset. A mismatch is a hard block. A
target with no ``File:`` at all is *not* a block -- ProofreadPage permits an
index without one -- but nothing then validates the correspondence, so the
report says so rather than implying a check happened.
"""


class SyncVerdict(str, Enum):
    """What would have to happen to this page for the two sides to agree.

    A different vocabulary from ``MatchOutcome`` on purpose. That enum answers
    "can these two revisions be linked", which is symmetric; this one answers
    "what would be written, and where", which is not. ``local_ahead`` is a fact
    about a pair; ``push`` is a fact about a direction.
    """

    in_sync = "in_sync"
    """The anchor names both heads. Nothing to do."""

    create = "create"
    """The target has no such page, or only a placeholder. The source's head
    would be written as a new page."""

    push = "push"
    """The source has revisions above the anchor and the target does not. The
    replay case: what the anchor exists to be the base of."""

    pull = "pull"
    """The target has revisions above the anchor and the source does not. The
    same operation pointed the other way, reported rather than hidden -- a sync
    that silently ignored inbound work would lose it."""

    diverged = "diverged"
    """Both sides moved after the anchor, or the transcriptions simply differ
    with the full history held. Needs a person (discussion §2)."""

    unlinked = "unlinked"
    """Both sides exist and hold content, but nothing says which revisions
    correspond. Not a conflict -- an unanswered question. ``detail`` carries the
    matcher's reason, which is what says whether fetching more would answer
    it."""

    source_missing = "source_missing"
    """The target has a page the source does not. Reported because a work that
    grew on the other side is exactly what a sync should surface, and silence
    would look like agreement."""

    unknown = "unknown"
    """A side has not been fetched, so there is nothing to compare. A fetch,
    not a verdict."""


ACTIONABLE = (SyncVerdict.create, SyncVerdict.push)
"""Verdicts a push in the requested direction would act on.

``pull`` is deliberately absent: it is real work, but it is work in the other
direction, and rolling it into the same count is how an inbound edit gets
quietly overwritten."""


class ScanStatus(str, Enum):
    ok = "ok"
    """Both sides' backing files are the same upload, by sha1."""

    mismatch = "mismatch"
    """Different uploads. A hard block: the page offsets do not correspond."""

    unverifiable = "unverifiable"
    """One side has no ``File:`` blob to compare. Not a block -- an index
    without a file is legal -- but correspondence then rests on page numbers
    with nothing validating them."""


@dataclass(frozen=True)
class ScanCheck:
    status: ScanStatus
    detail: str
    source_file: str | None = None
    target_file: str | None = None
    source_sha1: str | None = None
    target_sha1: str | None = None
    source_page_count: int | None = None
    target_page_count: int | None = None

    @property
    def blocks(self) -> bool:
        return self.status is ScanStatus.mismatch


@dataclass(frozen=True)
class SyncPage:
    """One page of the work, and what a sync would do to it."""

    verdict: SyncVerdict
    page_number: int | None
    source_title: str | None
    target_title: str | None = None

    pair_pk: int | None = None
    target_is_placeholder: bool = False

    source_revid: int | None = None
    target_revid: int | None = None
    anchor_source_revid: int | None = None
    anchor_target_revid: int | None = None
    rungs: int = 0

    source_ahead_by: int = 0
    target_ahead_by: int = 0
    detail: str | None = None

    @property
    def actionable(self) -> bool:
        return self.verdict in ACTIONABLE


@dataclass(frozen=True)
class SyncSide:
    site: str
    site_pk: int
    index_title: str
    exists: bool
    cached_pages: int = 0
    placeholder_pages: int = 0


@dataclass
class SyncReport:
    source: SyncSide
    target: SyncSide
    scan: ScanCheck
    pages: list[SyncPage] = field(default_factory=list)
    work_pk: int | None = None
    blockers: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for page in self.pages:
            out[page.verdict.value] = out.get(page.verdict.value, 0) + 1
        return out

    @property
    def actionable(self) -> int:
        return sum(1 for page in self.pages if page.actionable)


class SyncError(ValueError):
    """The report cannot be produced as asked."""


def build_report(
    session: Session,
    *,
    source_site: Site,
    target_site: Site,
    index_title: str,
    target_index_title: str | None = None,
) -> SyncReport:
    """Compare a work across two sites and say what a sync would do.

    Writes nothing, to either wiki or to the local model. Every fact here is
    read from the cache: the pagination came from ``list=proofreadpagesinindex``
    when the index was fetched (that is what wrote the placeholder rows), so
    reporting from the cache reports the authoritative pagination one step
    removed -- and a work fetched shallowly says so through
    ``cached_pages`` rather than looking complete.
    """
    target_index_title = target_index_title or index_title

    source_index = _index_page(session, source_site, index_title)
    if source_index is None:
        raise SyncError(
            f"{index_title} is not cached for {_site_name(source_site)}. "
            "A sync reports on what we hold: fetch the source index first."
        )
    target_index = _index_page(session, target_site, target_index_title)

    scan = _scan_check(session, source_index, target_index)

    source_children = index_children(session, source_site, index_title)
    target_children = (
        index_children(session, target_site, target_index_title)
        if target_index is not None
        else []
    )

    report = SyncReport(
        source=_side(session, source_site, index_title, source_index, source_children),
        target=_side(
            session, target_site, target_index_title, target_index, target_children
        ),
        scan=scan,
        work_pk=(
            work_pk_for(session, source_index, target_index)
            if target_index is not None
            else None
        ),
    )

    if scan.blocks:
        # Reported, and the page list still produced: a reviewer needs to see
        # *why* the offsets are suspect, and a bare "blocked" with no work
        # behind it is impossible to argue with.
        report.blockers.append(scan.detail)
    if target_index is None:
        report.blockers.append(
            f"{target_index_title} does not exist on {_site_name(target_site)}: "
            "the index itself would be created before any page."
        )

    report.pages = _page_reports(
        session,
        source_site=source_site,
        target_site=target_site,
        source_children=source_children,
        target_children=target_children,
    )
    return report


def _page_reports(
    session: Session,
    *,
    source_site: Site,
    target_site: Site,
    source_children: list[tuple[int | None, Page]],
    target_children: list[tuple[int | None, Page]],
) -> list[SyncPage]:
    """One row per page of the work, from either side.

    Pages line up on **page number within the index**, with title as a fallback
    only where a number is missing -- the same rule the matcher uses, and for
    the same reason: the two sides' titles can differ and the scan offset is
    what has to correspond.
    """
    target_by_number = {n: page for n, page in target_children if n is not None}
    target_by_title = {canonical_title(p.title): p for _, p in target_children}

    rows: list[SyncPage] = []
    seen_targets: set[int] = set()

    for number, source_page in source_children:
        target_page = target_by_number.get(number) if number is not None else None
        if target_page is None:
            target_page = target_by_title.get(canonical_title(source_page.title))
        if target_page is not None:
            seen_targets.add(target_page.pk)
        rows.append(_page_report(session, number, source_page, target_page))

    # Pages the target has and the source does not. A work that grew on the
    # other side is precisely what a sync should surface.
    for number, target_page in target_children:
        if target_page.pk in seen_targets:
            continue
        rows.append(
            SyncPage(
                verdict=SyncVerdict.source_missing,
                page_number=number,
                source_title=None,
                target_title=target_page.title,
                target_revid=target_page.revid,
                detail="only on the target side",
            )
        )

    rows.sort(key=lambda row: (row.page_number is None, row.page_number or 0))
    return rows


def _page_report(
    session: Session,
    number: int | None,
    source_page: Page,
    target_page: Page | None,
) -> SyncPage:
    base = {
        "page_number": number,
        "source_title": source_page.title,
        "source_revid": source_page.revid,
    }

    if target_page is None:
        return SyncPage(
            verdict=SyncVerdict.create,
            target_title=None,
            detail="no page on the target side",
            **base,
        )

    base["target_title"] = target_page.title
    base["target_revid"] = target_page.revid

    pairing = find_pair(session, source_page.pk, target_page.pk)
    if pairing is not None:
        base["pair_pk"] = pairing.pk
        base["rungs"] = len(
            ladder(session, page_pk=source_page.pk, other_page_pk=target_page.pk)
        )

    if head_revision(session, target_page) is None:
        placeholder = _is_placeholder(session, target_page)
        return SyncPage(
            verdict=SyncVerdict.create if placeholder else SyncVerdict.unknown,
            target_is_placeholder=placeholder,
            detail=(
                "placeholder: paginated by the index, never transcribed"
                if placeholder
                else "target has no cached revision -- fetch it before syncing"
            ),
            **base,
        )
    if head_revision(session, source_page) is None:
        return SyncPage(
            verdict=SyncVerdict.unknown,
            detail=(
                "source is a placeholder: nothing to write"
                if _is_placeholder(session, source_page)
                else "source has no cached revision"
            ),
            **base,
        )

    return _compared(session, source_page, target_page, base)


def _compared(
    session: Session, source_page: Page, target_page: Page, base: dict
) -> SyncPage:
    """Turn the symmetric matcher's answer into a directional one.

    ``compare_pages`` is called source-as-local, so its ``local`` is our source
    and its ``remote`` our target -- which is the whole translation: the
    matcher's ``local_ahead`` becomes ``push``, its ``remote_ahead`` becomes
    ``pull``.
    """
    proposal = compare_pages(session, source_page, target_page)
    anchor = find_anchor(session, source_page, target_page)
    if anchor is not None:
        base["anchor_source_revid"] = anchor.local_revision.revid
        base["anchor_target_revid"] = anchor.remote_revision.revid
        base["source_ahead_by"] = anchor.local_ahead_by
        base["target_ahead_by"] = anchor.remote_ahead_by

    outcome = proposal.outcome
    if outcome is MatchOutcome.already_linked:
        # The matcher stops at "linked" without saying how far the heads have
        # moved since; the ladder's own anchor is what answers that.
        return _from_anchor(session, source_page, target_page, base)
    if outcome is MatchOutcome.same:
        return SyncPage(verdict=SyncVerdict.in_sync, **base)
    if outcome is MatchOutcome.local_ahead:
        return SyncPage(
            verdict=SyncVerdict.push,
            detail=f"{base.get('source_ahead_by', 0)} revision(s) to replay",
            **base,
        )
    if outcome is MatchOutcome.remote_ahead:
        return SyncPage(
            verdict=SyncVerdict.pull,
            detail=f"{base.get('target_ahead_by', 0)} revision(s) inbound",
            **base,
        )
    if outcome is MatchOutcome.diverged:
        return SyncPage(
            verdict=SyncVerdict.diverged,
            detail=proposal.detail or "both sides moved after their last agreement",
            **base,
        )
    return SyncPage(
        verdict=SyncVerdict.unlinked,
        detail=proposal.detail or outcome.value,
        **base,
    )


def _from_anchor(
    session: Session, source_page: Page, target_page: Page, base: dict
) -> SyncPage:
    """A pair that is already linked: the verdict is the distance from its
    anchor, not what a fresh comparison would propose."""
    rungs = ladder(session, page_pk=source_page.pk, other_page_pk=target_page.pk)
    source_head = head_revision(session, source_page)
    target_head = head_revision(session, target_page)
    anchor = rungs[-1] if rungs else None
    if anchor is None:  # pragma: no cover - already_linked implies a rung
        return SyncPage(verdict=SyncVerdict.unlinked, **base)

    anchored = {anchor.local_revision_pk, anchor.remote_revision_pk}
    at_source_head = source_head is not None and source_head.pk in anchored
    at_target_head = target_head is not None and target_head.pk in anchored

    if at_source_head and at_target_head:
        return SyncPage(verdict=SyncVerdict.in_sync, **base)
    if at_target_head:
        return SyncPage(
            verdict=SyncVerdict.push, detail="source has moved past the anchor", **base
        )
    if at_source_head:
        return SyncPage(
            verdict=SyncVerdict.pull, detail="target has moved past the anchor", **base
        )
    return SyncPage(
        verdict=SyncVerdict.diverged,
        detail="both sides have moved past the anchor",
        **base,
    )


def _is_placeholder(session: Session, page: Page) -> bool:
    """A row for a page that is known not to exist on the wiki.

    The fan-out writes these for slots ProofreadPage paginates but nobody has
    transcribed. Having no revision *and* ``fetch_status=done`` is the
    distinction that matters: we asked, and the answer was "absent" -- as
    against a row we have simply not got to, where the answer is unknown.

    "Has no revision" is read through the revision store rather than off
    ``Page.revid``. The head columns on ``Page`` are a denormalisation with
    more than one writer (TODO: normalise them behind ``head_revision``), and
    trusting them here would make this answer "create" for a page that has
    revisions, on any path that filled one and not the other.
    """
    return head_revision(session, page) is None and page.fetch_status == FetchState.done


def _index_page(session: Session, site: Site, title: str) -> Page | None:
    return session.exec(
        select(Page).where(
            Page.site_pk == site.pk,
            Page.title == title,
            Page.namespace_role == NsRole.index,
        )
    ).first()


def _side(
    session: Session,
    site: Site,
    index_title: str,
    index_page: Page | None,
    children: list[tuple[int | None, Page]],
) -> SyncSide:
    placeholders = sum(1 for _, page in children if _is_placeholder(session, page))
    return SyncSide(
        site=_site_name(site),
        site_pk=site.pk,
        index_title=index_title,
        exists=index_page is not None,
        cached_pages=len(children),
        placeholder_pages=placeholders,
    )


def _scan_check(
    session: Session, source_index: Page, target_index: Page | None
) -> ScanCheck:
    """Discussion §6: do the two sides transcribe the same upload?

    Compared by ``FileBlob.file_sha1``, the hash of the binary -- not the page
    count, which two different scans of the same book will happily share while
    starting on different leaves.
    """
    source_file, source_blob = _file_of(session, source_index)
    target_file, target_blob = (
        _file_of(session, target_index) if target_index is not None else (None, None)
    )

    common = {
        "source_file": source_file,
        "target_file": target_file,
        "source_sha1": source_blob.file_sha1 if source_blob else None,
        "target_sha1": target_blob.file_sha1 if target_blob else None,
        "source_page_count": source_blob.page_count if source_blob else None,
        "target_page_count": target_blob.page_count if target_blob else None,
    }

    if source_blob is None or target_blob is None:
        missing = "target" if source_blob is not None else "source"
        if source_blob is None and target_blob is None:
            missing = "neither side"
        return ScanCheck(
            status=ScanStatus.unverifiable,
            detail=(
                f"no File: blob held for the {missing} index, so the scan check "
                "cannot run. An index without a file is legal, but page "
                "correspondence then rests on page numbers with nothing "
                "validating it."
            ),
            **common,
        )
    if source_blob.file_sha1 is None or target_blob.file_sha1 is None:
        return ScanCheck(
            status=ScanStatus.unverifiable,
            detail="a File: blob has no sha1 recorded; download it to check",
            **common,
        )
    if source_blob.file_sha1 != target_blob.file_sha1:
        return ScanCheck(
            status=ScanStatus.mismatch,
            detail=(
                "the two sides' backing scans are different uploads "
                f"({source_blob.file_sha1[:12]} vs {target_blob.file_sha1[:12]}), "
                "so page N on one is not page N on the other and every verdict "
                "below is off by an unknown offset"
            ),
            **common,
        )
    return ScanCheck(
        status=ScanStatus.ok,
        detail="both sides transcribe the same upload",
        **common,
    )


def _file_of(session: Session, index_page: Page) -> tuple[str | None, FileBlob | None]:
    """The ``File:`` backing an ``Index:``, and its downloaded blob record.

    By title -- ``Index:Foo.djvu`` -> ``File:Foo.djvu`` -- which is how the
    fetch fan-out finds it too. The scan may live on the site itself or, for a
    Wikimedia wiki, on Commons; both end up as a ``File:`` row on the site that
    fetched it.
    """
    _, _, basename = index_page.title.partition(":")
    file_title = f"File:{basename}"
    page = session.exec(
        select(Page).where(Page.site_pk == index_page.site_pk, Page.title == file_title)
    ).first()
    if page is None:
        return file_title, None
    blob = session.exec(select(FileBlob).where(FileBlob.page_pk == page.pk)).first()
    return file_title, blob


def _site_name(site: Site) -> str:
    return site.label or f"{site.family}:{site.code}"


def work_pk_for(session: Session, source_index: Page, target_index: Page) -> int | None:
    """The tracked work for two index pages, if they are tracked."""
    pairing: PageLink | None = find_pair(session, source_index.pk, target_index.pk)
    if pairing is None:
        return None
    work = find_index_link(session, source_index.pk, target_index.pk)
    return work.pk if work else None
