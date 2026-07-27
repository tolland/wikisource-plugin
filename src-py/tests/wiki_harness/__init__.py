from wiki_harness.api import EditResult, RevisionInfo, WikiApi, WikiApiError
from wiki_harness.endpoint import WikiEndpoint
from wiki_harness.stack import (
    StackConfig,
    WikiStack,
    docker_available,
    wait_for_mediawiki,
)

"""Test harness for driving one or two real MediaWiki+ProofreadPage instances.

Used by the cross-wiki sync tests, which need behaviour ``FakeWikiClient``
cannot model: revision history, MediaWiki's sha1 semantics, conditional edits
(``createonly``/``basetimestamp``) and ``undo``.
"""

__all__ = [
    "EditResult",
    "RevisionInfo",
    "StackConfig",
    "WikiApi",
    "WikiApiError",
    "WikiEndpoint",
    "WikiStack",
    "docker_available",
    "wait_for_mediawiki",
]
