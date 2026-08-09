from dataclasses import dataclass

from wtbot.content_model.comparison import Comparison, Significance

"""Plain wikitext: the whole body is the comparable text, and there is no
embedded metadata. Also the fallback for content models we have no special
knowledge of, where treating everything as comparable is the safe default --
it can report a spurious difference, never a spurious sameness."""


def normalise_newlines(text: str) -> str:
    """Only line endings are normalised.

    Deliberately conservative: stripping trailing whitespace or collapsing
    blank lines would hide real differences, and in wikitext a trailing space
    can change rendering. A comparison that is too strict shows a reviewer a
    diff; one that is too loose promotes a change nobody saw.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class WikitextDocument:
    content_model: str = "wikitext"
    text: str = ""

    @classmethod
    def parse(cls, text: str) -> "WikitextDocument":
        return cls(text=text)

    @property
    def comparable_text(self) -> str:
        return normalise_newlines(self.text)

    @property
    def canonical_text(self) -> str:
        """The same thing: plain wikitext has no metadata to fold in."""
        return self.comparable_text

    def compare(self, other) -> Comparison:
        equal = self.comparable_text == other.comparable_text
        return Comparison(
            significance=Significance.identical if equal else Significance.content,
            text_equal=equal,
        )

    def validation_errors(self) -> tuple[str, ...]:
        return ()
