from wtbot.content_model.comparison import (
    Comparison,
    FieldDifference,
    Significance,
)
from wtbot.content_model.digest import comparable_sha1
from wtbot.content_model.document import ContentDocument, parse_document
from wtbot.content_model.proofread_page import ProofreadPageDocument
from wtbot.content_model.wikitext import WikitextDocument

"""Content-model-aware comparison of page bodies.

Cross-site sameness cannot be decided by hashing -- a ``proofread-page`` body
embeds a site-specific username and that wiki's proofreading level in its own
text, both of which change as the page is proofread. Comparison therefore has
to know what the parts of a body mean. See ``document.py``.
"""

__all__ = [
    "Comparison",
    "ContentDocument",
    "FieldDifference",
    "ProofreadPageDocument",
    "Significance",
    "WikitextDocument",
    "comparable_sha1",
    "parse_document",
]
