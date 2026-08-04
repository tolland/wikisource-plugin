from dataclasses import dataclass
from enum import Enum

"""The result of comparing two documents of the same content model.

Deliberately not a boolean. Two `proofread-page` bodies can be the same
transcription while differing in the metadata embedded in their text, and the
promotion path needs to tell those cases apart: "same words, different
proofreading state" is a different decision from "different words".
"""


class Significance(str, Enum):
    """How much the difference matters, from the promotion path's view."""

    identical = "identical"
    """Nothing differs, including metadata."""

    metadata_only = "metadata_only"
    """Same comparable text; only fields excluded from comparison differ.

    The common cross-site case: the same transcription attributed to a
    different username, because ``pagequality user=`` names an account on
    whichever wiki last set the level.
    """

    metadata_significant = "metadata_significant"
    """Same comparable text, but a metadata field that carries meaning differs.

    For ``proofread-page`` this is the proofreading level. Equal words do not
    make it safe to overwrite: pushing level 2 over a page someone marked
    level 4 discards their assessment.
    """

    content = "content"
    """The comparable text itself differs."""


@dataclass(frozen=True)
class FieldDifference:
    field: str
    left: str | None
    right: str | None
    comparable: bool
    """False for fields deliberately excluded from the comparison -- recorded
    so a reviewer can see them, never used to decide sameness."""

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.field}: {self.left!r} -> {self.right!r}"


@dataclass(frozen=True)
class Comparison:
    significance: Significance
    text_equal: bool
    differences: tuple[FieldDifference, ...] = ()
    quality_delta: int | None = None
    """right.level - left.level for proofread-page, else None. Negative means
    the right-hand side asserts a *lower* proofreading state, which promotion
    must never do."""

    @property
    def same_transcription(self) -> bool:
        """True when the words match, whatever the metadata says."""
        return self.text_equal

    @property
    def is_downgrade(self) -> bool:
        return self.quality_delta is not None and self.quality_delta < 0

    def comparable_differences(self) -> tuple[FieldDifference, ...]:
        return tuple(d for d in self.differences if d.comparable)
