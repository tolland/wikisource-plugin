from wiki_harness.api import EditResult, RevisionInfo, WikiApi, WikiApiError
from wiki_harness.dumps import (
    SCANS_DIR,
    DumpPage,
    DumpRevision,
    read_dump,
    read_dump_text,
    scan_dump,
)
from wiki_harness.endpoint import WikiEndpoint
from wiki_harness.pwb import PwbHarness, pywikibot_harness
from wiki_harness.scenarios import (
    CANADIAN_PATENT_DUMP,
    CANADIAN_PATENT_INDEX,
    CANADIAN_PATENT_SCAN,
    LOCAL_EDIT_MARKER,
    PAGE_2,
    CopiedWork,
    NotSeeded,
    assert_seeded,
    copy_page_to_local,
    diverge_locally,
    reconcile_to_upstream,
)
from wiki_harness.stack import (
    StackConfig,
    WikiStack,
    docker_available,
    pair_config,
    wait_for_mediawiki,
)

"""Test harness for driving one or two real MediaWiki+ProofreadPage instances.

Used by the cross-wiki sync tests, which need behaviour ``FakeWikiClient``
cannot model: revision history, MediaWiki's sha1 semantics, conditional edits
(``createonly``/``basetimestamp``) and ``undo``.
"""

__all__ = [
    "CANADIAN_PATENT_DUMP",
    "CANADIAN_PATENT_INDEX",
    "CANADIAN_PATENT_SCAN",
    "LOCAL_EDIT_MARKER",
    "PAGE_2",
    "SCANS_DIR",
    "CopiedWork",
    "NotSeeded",
    "assert_seeded",
    "DumpPage",
    "DumpRevision",
    "EditResult",
    "PwbHarness",
    "RevisionInfo",
    "StackConfig",
    "WikiApi",
    "WikiApiError",
    "WikiEndpoint",
    "WikiStack",
    "copy_page_to_local",
    "diverge_locally",
    "docker_available",
    "pair_config",
    "pywikibot_harness",
    "read_dump",
    "read_dump_text",
    "reconcile_to_upstream",
    "scan_dump",
    "wait_for_mediawiki",
]
