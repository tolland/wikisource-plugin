import re
from dataclasses import dataclass

from wtbot.content_model.comparison import Comparison, FieldDifference, Significance
from wtbot.content_model.wikitext import normalise_newlines

"""``proofread-page``: a transcription with its proofreading state embedded in
its own text.

    <noinclude><pagequality level="3" user="Hesperian" />HEADER</noinclude>
    BODY
    <noinclude>FOOTER</noinclude>

The two embedded attributes are handled differently, because they mean
different things:

- ``user`` names an account on *that* wiki. It must be present -- ProofreadPage
  writes it whenever the level is set -- but it can never be compared across
  sites, and comparing it within one site says nothing about the transcription.
- ``level`` is the proofreading state, and it is *significant and directional*.
  Two pages with identical words are still not interchangeable if one is marked
  Proofread and the other Not proofread: pushing the lower one over the higher
  discards somebody's assessment.

Header, body and footer are all comparable. The header is not only the
pagequality tag -- running headers live there too -- so it is compared with the
tag removed rather than being ignored wholesale.
"""

QUALITY_LEVELS = range(0, 5)

_LEADING_NOINCLUDE = re.compile(r"\A<noinclude>(?P<header>.*?)</noinclude>", re.DOTALL)
_TRAILING_NOINCLUDE = re.compile(r"<noinclude>(?P<footer>.*?)</noinclude>\Z", re.DOTALL)
_PAGEQUALITY = re.compile(r"<pagequality\b(?P<attrs>[^>]*?)/?>", re.DOTALL)
_ATTR = re.compile(r"(?P<name>\w+)\s*=\s*\"(?P<value>[^\"]*)\"")


@dataclass(frozen=True)
class ProofreadPageDocument:
    header: str = ""
    body: str = ""
    footer: str = ""
    level: int | None = None
    user: str | None = None
    content_model: str = "proofread-page"

    @classmethod
    def parse(cls, text: str) -> "ProofreadPageDocument":
        """Split a serialized body into its parts.

        Forgiving by design: a ``Page:`` whose text was written without the
        wrappers (pasted, or created outside ProofreadPage) parses as all body
        and no metadata, rather than raising. A parse failure here would block
        a comparison the reviewer could otherwise have looked at.
        """
        remainder = normalise_newlines(text)

        header_block = ""
        leading = _LEADING_NOINCLUDE.match(remainder)
        if leading is not None:
            header_block = leading.group("header")
            remainder = remainder[leading.end() :]

        footer = ""
        trailing = _TRAILING_NOINCLUDE.search(remainder)
        if trailing is not None:
            footer = trailing.group("footer")
            remainder = remainder[: trailing.start()]

        level, user, header = cls._split_pagequality(header_block)
        return cls(header=header, body=remainder, footer=footer, level=level, user=user)

    @staticmethod
    def _split_pagequality(header_block: str) -> tuple[int | None, str | None, str]:
        match = _PAGEQUALITY.search(header_block)
        if match is None:
            return None, None, header_block

        attrs = dict(
            (m.group("name"), m.group("value")) for m in _ATTR.finditer(match["attrs"])
        )
        raw_level = attrs.get("level")
        level = int(raw_level) if raw_level and raw_level.isdigit() else None
        # `user` may legitimately be present-but-empty; keep that distinct from
        # absent, since validation cares about the difference.
        user = attrs.get("user")

        remaining_header = header_block[: match.start()] + header_block[match.end() :]
        return level, user, remaining_header

    # -- comparison -------------------------------------------------------

    @property
    def comparable_text(self) -> str:
        """Header (without the pagequality tag), body and footer.

        Separated by a character that cannot occur in wikitext, so a body
        ending in what looks like a header cannot alias with a different split.
        """
        return "\0".join((self.header, self.body, self.footer))

    @property
    def canonical_text(self) -> str:
        """The comparable text with the proofreading level folded back in.

        ``user`` is dropped -- it names an account on one wiki, so keeping it
        would make the same transcription canonicalise differently on the two
        sides, which is the whole problem this form exists to sidestep.
        ``level`` is kept, and kept *distinct from absent*, because it is
        significant: identical words at level 2 and level 4 are not the same
        content, and treating them as such would let a push discard somebody's
        assessment.

        Joined rather than re-serialized: round-tripping through
        ``serialize()`` would put the parts back inside ``<noinclude>``
        wrappers, where a body containing a wrapper of its own could alias with
        a different header/body/footer split. Same reason as
        :attr:`comparable_text`, which this extends.
        """
        level = "" if self.level is None else str(self.level)
        return "\0".join((level, self.header, self.body, self.footer))

    def compare(self, other) -> Comparison:
        if not isinstance(other, ProofreadPageDocument):
            equal = self.comparable_text == other.comparable_text
            return Comparison(
                significance=Significance.identical if equal else Significance.content,
                text_equal=equal,
            )

        differences: list[FieldDifference] = []
        for field in ("header", "body", "footer"):
            left, right = getattr(self, field), getattr(other, field)
            if left != right:
                differences.append(FieldDifference(field, left, right, comparable=True))

        if self.level != other.level:
            differences.append(
                FieldDifference(
                    "level",
                    _as_text(self.level),
                    _as_text(other.level),
                    comparable=True,
                )
            )
        if self.user != other.user:
            # Recorded for the reviewer, never used to decide sameness.
            differences.append(
                FieldDifference("user", self.user, other.user, comparable=False)
            )

        text_equal = self.comparable_text == other.comparable_text
        if not text_equal:
            significance = Significance.content
        elif self.level != other.level:
            significance = Significance.metadata_significant
        elif differences:
            significance = Significance.metadata_only
        else:
            significance = Significance.identical

        return Comparison(
            significance=significance,
            text_equal=text_equal,
            differences=tuple(differences),
            quality_delta=_delta(self.level, other.level),
        )

    # -- validation -------------------------------------------------------

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.level is not None:
            if self.level not in QUALITY_LEVELS:
                errors.append(f"pagequality level {self.level} is out of range 0-4")
            if not self.user:
                # ProofreadPage always writes a user alongside a level; a body
                # without one did not come from the extension and will not
                # round-trip.
                errors.append("pagequality level is set but user is empty")
        return tuple(errors)

    def with_user(self, user: str) -> "ProofreadPageDocument":
        """The same document attributed to a different account.

        The transformation a promotion applies: the local username may not
        exist on the target, and the level is being asserted by whoever pushes.
        """
        return ProofreadPageDocument(
            header=self.header,
            body=self.body,
            footer=self.footer,
            level=self.level,
            user=user,
        )

    def serialize(self) -> str:
        if self.level is None:
            return f"<noinclude>{self.header}</noinclude>{self.body}<noinclude>{self.footer}</noinclude>"
        tag = f'<pagequality level="{self.level}" user="{self.user or ""}" />'
        return (
            f"<noinclude>{tag}{self.header}</noinclude>"
            f"{self.body}"
            f"<noinclude>{self.footer}</noinclude>"
        )


def _as_text(level: int | None) -> str | None:
    return None if level is None else str(level)


def _delta(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return right - left
