from typing import Protocol, runtime_checkable

from wtbot.content_model.comparison import Comparison

"""The content-model-aware comparison seam.

Cross-site sameness cannot be decided by hashing: a ``proofread-page`` body
carries ``<pagequality level="N" user="X" />`` in its own text, where the user
names an account on that wiki and the level is that wiki's proofreading state.
Proofreading a page locally changes both, so two identical transcriptions
routinely hash differently -- and increasingly so as the work progresses.

A document therefore knows how to compare *itself*: which parts are the
transcription, which are metadata that matters (the level), and which are
metadata that must be present but is not comparable (the user).
"""


@runtime_checkable
class ContentDocument(Protocol):
    """One page body, parsed according to its content model."""

    content_model: str

    @property
    def comparable_text(self) -> str:
        """The parts that decide whether this is the same transcription."""
        ...

    def compare(self, other: "ContentDocument") -> Comparison: ...

    def validation_errors(self) -> tuple[str, ...]:
        """Why this body is not safe to push, if it isn't."""
        ...


def parse_document(text: str, content_model: str | None) -> ContentDocument:
    """Parse a body according to its content model.

    Unknown models fall back to plain wikitext, which compares whole-text and
    has no metadata -- lossless, just less informative.
    """
    # Imported here so each model module can import the protocol without a
    # circular import back through this dispatcher.
    from wtbot.content_model.proofread_page import ProofreadPageDocument
    from wtbot.content_model.wikitext import WikitextDocument

    if content_model == ProofreadPageDocument.content_model:
        return ProofreadPageDocument.parse(text)
    return WikitextDocument.parse(text)
