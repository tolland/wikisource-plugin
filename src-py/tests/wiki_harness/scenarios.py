from dataclasses import dataclass

from wiki_harness.api import WikiApi
from wiki_harness.stack import WikiStack

"""Named cross-wiki situations, built on the two-wiki harness.

These exist twice over: as the setup for the sync tests, and as something a
human can stand up and click around in (``python -m wiki_harness``). Keeping
one definition means the thing being debugged by hand is the same thing CI
asserts against -- a scenario that only exists inside a test body cannot be
reproduced when it fails, and a fixture that only exists in a shell script
drifts from what is tested.

Every builder is idempotent: run it twice and the second run is a no-op, so a
reused stack (``--reuse-wikisource``) does not accumulate revisions and quietly
break the tests that count them.
"""

CANADIAN_PATENT_INDEX = "Index:Canadian patent 29537.djvu"
CANADIAN_PATENT_SCAN = "File:Canadian patent 29537.djvu"
CANADIAN_PATENT_DUMP = "Canadian_patent_29537_all.xml"
PAGE_2 = "Page:Canadian patent 29537.djvu/2"

# Marks a body this harness wrote, so an idempotency check can tell "already
# built" from "someone edited it".
LOCAL_EDIT_MARKER = "<!-- harness: local divergence -->"


@dataclass(frozen=True)
class CopiedWork:
    """A page present on both wikis, with the revision ids of each side."""

    title: str
    upstream_revid: int
    local_revid: int


def seed_upstream_work(stack: WikiStack, upstream: WikiApi) -> None:
    """Load the real Canadian patent work into the upstream wiki.

    Imported rather than API-written: importDump preserves each revision's
    text, timestamp and contributor, and therefore its sha1. An API copy would
    flatten the history to a single revision, which is precisely the property
    the sync tests need to be real.
    """
    if upstream.exists(CANADIAN_PATENT_INDEX):
        return
    stack.import_scans("upstream", extension="djvu")
    stack.import_dump("upstream", CANADIAN_PATENT_DUMP)
    stack.rebuild_links("upstream")


def copy_page_to_local(
    upstream: WikiApi, local: WikiApi, title: str = PAGE_2
) -> CopiedWork:
    """Copy one page's *current* body upstream -> local, as a fresh creation.

    This is the API-level copy on purpose, not an import: it is what a
    downward promotion would do, and it is the case where the two sides hold
    the same transcription under different attribution. ProofreadPage rewrites
    ``pagequality user=`` to the saving account, so the local copy is expected
    to differ from its source in exactly that field -- which is the whole
    reason correspondence is asserted rather than hashed.
    """
    body = upstream.page_text(title)
    if body is None:
        raise RuntimeError(f"{title} does not exist upstream; seed it first")

    if not local.exists(title):
        local.edit(
            title, body, summary="harness: copied from upstream", createonly=True
        )

    return CopiedWork(
        title=title,
        upstream_revid=upstream.revisions(title, limit=1)[0].revid,
        local_revid=local.revisions(title, limit=1)[0].revid,
    )


def diverge_locally(local: WikiApi, title: str = PAGE_2) -> int:
    """Edit the local copy so the two sides hold different transcriptions.

    Returns the new local revid. Idempotent via ``LOCAL_EDIT_MARKER``: a second
    call returns the existing head rather than stacking another revision.
    """
    revisions = local.revisions(title, limit=1, with_content=True)
    if not revisions:
        raise RuntimeError(f"{title} does not exist locally; copy it first")
    head = revisions[0]
    if LOCAL_EDIT_MARKER in (head.content or ""):
        return head.revid

    body = f"{head.content}\n{LOCAL_EDIT_MARKER}\nAn addition made only locally.\n"
    return local.edit(title, body, summary="harness: local divergence").revid


def reconcile_to_upstream(
    upstream: WikiApi, local: WikiApi, title: str = PAGE_2
) -> int:
    """Make the local body match upstream's again -- the forward re-anchoring
    of discussion section 2, performed by hand in the real workflow.

    Returns the resulting local revid, which is the one a new
    ``origin=reconciled`` link should be asserted against.
    """
    body = upstream.page_text(title)
    if body is None:
        raise RuntimeError(f"{title} does not exist upstream")
    local_head = local.revisions(title, limit=1, with_content=True)[0]
    if local_head.content == body:
        return local_head.revid
    return local.edit(title, body, summary="harness: reconciled to upstream").revid
