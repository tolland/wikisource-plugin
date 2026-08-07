from dataclasses import dataclass

from wiki_harness.api import WikiApi

"""Deltas applied to the two-wiki harness, and the assertion that its base is
what it claims to be.

The **base state** -- two wikis holding the same works, imported with real
revision history -- is built by the containers themselves from ``SEED_DUMPS``/
``SEED_SCANS`` (see docker/mediawiki/start-wikisource.sh). Both wikis read the
same compose anchor, so they are identical because they are configured
identically, not because a builder out here remembered to run twice. That is
what this module used to get wrong: it seeded upstream only, and every "the two
sides diverged" fixture was really "the two sides were never the same".

What is left here is the **deltas** -- the differences a test deliberately
creates. They are ordinary functions, not a scenario enum with a chain of
conditionals: a test that wants divergence calls ``diverge_locally`` and says so
in one line, rather than naming a scenario whose meaning has to be traced
through fallthroughs.

Every delta is idempotent, so a reused stack does not accumulate revisions the
tests count.
"""

CANADIAN_PATENT_INDEX = "Index:Canadian patent 29537.djvu"
CANADIAN_PATENT_SCAN = "File:Canadian patent 29537.djvu"
CANADIAN_PATENT_DUMP = "Canadian_patent_29537_all.xml"
PAGE_2 = "Page:Canadian patent 29537.djvu/2"

SCRATCH_PAGE = "Page:Harness scratch.djvu/1"
"""Where mutating tests work.

**The seeded work is read-only.** Nothing tears the stack down any more, so a
test that edits the imported pages leaves the pair diverged for the next run --
and the run after that starts from a base that is no longer the base. That is
not a teardown problem to be solved by going back to teardown; it is a test
writing to shared state it does not own.

A `Page:` outside the imported work is still a real `proofread-page` -- the
content model comes from the namespace, and ProofreadPage permits a `Page:`
with no backing `File:` (discussion section 6) -- so the deltas exercise the
same content model without touching anything another test reads."""

# Marks a body this harness wrote, so an idempotency check can tell "already
# applied" from "someone edited it".
LOCAL_EDIT_MARKER = "<!-- harness: local divergence -->"


class NotSeeded(RuntimeError):
    """The wiki is up but does not hold the works the harness expects."""


@dataclass(frozen=True)
class CopiedWork:
    """A page present on both wikis, with the revision ids of each side."""

    title: str
    upstream_revid: int
    local_revid: int


def assert_seeded(api: WikiApi, *, role: str = "wiki") -> WikiApi:
    """Fail loudly if a wiki came up without its content.

    Seeding is the container's job now, so a test's only responsibility is to
    notice when it did not happen -- and to say why rather than failing later
    on a missing page. The usual cause is a stack started with ``SEED_DUMPS``
    blanked, or one whose healthcheck was bypassed while an import was still
    running.
    """
    if not api.exists(CANADIAN_PATENT_INDEX):
        raise NotSeeded(
            f"{role} does not hold {CANADIAN_PATENT_INDEX}. Start the pair with "
            "`docker compose --profile pair up -d --wait` and check SEED_DUMPS."
        )
    return api


def copy_page_to_local(
    upstream: WikiApi, local: WikiApi, title: str = SCRATCH_PAGE
) -> CopiedWork:
    """Replace the local page with an API-level copy of upstream's head.

    Deletes first, so this is always a *creation*: the point is to produce what
    a downward promotion produces -- one revision instead of a history, and
    ``pagequality user=`` reattributed to the saving account -- rather than the
    imported mirror, which is identical on both sides by construction. Those
    are different situations and the tests need both.

    Deleting rather than editing also makes it idempotent in the only sense
    that matters across runs: the result does not depend on what the previous
    run left behind.
    """
    body = upstream.page_text(title)
    if body is None:
        raise NotSeeded(f"{title} does not exist upstream")

    if local.exists(title):
        local.delete(title, reason="harness: replacing with an API-level copy")
    local.edit(title, body, summary="harness: copied from upstream")

    return CopiedWork(
        title=title,
        upstream_revid=upstream.revisions(title, limit=1)[0].revid,
        local_revid=local.revisions(title, limit=1)[0].revid,
    )


def create_scratch_pair(
    upstream: WikiApi,
    local: WikiApi,
    *,
    source_title: str = PAGE_2,
    title: str = SCRATCH_PAGE,
) -> CopiedWork:
    """Put a disposable page pair on both wikis, bodied from the seeded work.

    Creates only -- it never deletes, so ``local`` may be an ordinary
    (non-sysop) account. Pass a *different* account than upstream's, such as
    the ``local_promoter`` fixture, to get the cross-site norm: the same
    transcription attributed to a username that exists on one wiki only.
    Constructing that beats inheriting it from however the fixture happened to
    be imported, and it holds whether or not ProofreadPage rewrites
    ``pagequality user=`` on save.

    Call ``remove_scratch_pair`` with sysop accounts first if the pages might
    already exist; deletion is a privilege the writer here is not assumed to
    have.
    """
    body = upstream.page_text(source_title)
    if body is None:
        raise NotSeeded(f"{source_title} does not exist upstream")

    upstream.edit(title, body, summary=f"harness: scratch copy of {source_title}")
    local.edit(
        title,
        upstream.page_text(title),
        summary=f"harness: scratch copy of {source_title}",
    )

    return CopiedWork(
        title=title,
        upstream_revid=upstream.revisions(title, limit=1)[0].revid,
        local_revid=local.revisions(title, limit=1)[0].revid,
    )


def remove_scratch_pair(*apis: WikiApi, title: str = SCRATCH_PAGE) -> None:
    """Delete the disposable pages. Needs sysop accounts.

    Called before creating as well as after, so a run that died mid-test does
    not hand the next one a page with an unexpected history.
    """
    for api in apis:
        if api.exists(title):
            api.delete(title, reason="harness: scratch cleanup")


def diverge_locally(local: WikiApi, title: str = SCRATCH_PAGE) -> int:
    """Edit the local copy so the two sides hold different transcriptions.

    Returns the new local revid. Idempotent via ``LOCAL_EDIT_MARKER``: a second
    call returns the existing head rather than stacking another revision.
    """
    revisions = local.revisions(title, limit=1, with_content=True)
    if not revisions:
        raise NotSeeded(f"{title} does not exist locally")
    head = revisions[0]
    if LOCAL_EDIT_MARKER in (head.content or ""):
        return head.revid

    body = f"{head.content}\n{LOCAL_EDIT_MARKER}\nAn addition made only locally.\n"
    return local.edit(title, body, summary="harness: local divergence").revid


def reconcile_to_upstream(
    upstream: WikiApi, local: WikiApi, title: str = SCRATCH_PAGE
) -> int:
    """Make the local body match upstream's again -- the forward re-anchoring
    of discussion section 2, performed by hand in the real workflow.

    Returns the resulting local revid, which is the one a new
    ``origin=reconciled`` link should be asserted against.
    """
    body = upstream.page_text(title)
    if body is None:
        raise NotSeeded(f"{title} does not exist upstream")
    local_head = local.revisions(title, limit=1, with_content=True)[0]
    if local_head.content == body:
        return local_head.revid
    return local.edit(title, body, summary="harness: reconciled to upstream").revid
