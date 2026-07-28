from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from wtbot.wiki.sha1 import content_sha1_base36

"""Reader for the MediaWiki XML export fixtures under tests/fixtures/scans.

Exists so tests can assert against what a dump *actually contains* rather than
against hashes copied into a test file by hand -- which is how the
proofread-page serialization discrepancy (see ``declared_sha1`` below) went
unnoticed.
"""

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SCANS_DIR = FIXTURES_DIR / "scans"


@dataclass(frozen=True)
class DumpRevision:
    revid: int
    timestamp: str
    user: str | None
    comment: str | None
    declared_sha1: str | None
    bytes: str
    """``rev_sha1`` as the source wiki stored it, base-36.

    For ``proofread-page`` revisions saved before ProofreadPage's stored
    serialization was normalised, this does **not** equal the hash of ``text``:
    the wiki froze it over the bytes as saved, while the export serves the
    content in today's format. Verified against live en.wikisource, not just
    this fixture. Use :attr:`content_sha1` for anything that must match a hash
    computed elsewhere.
    """
    text: str

    @property
    def content_sha1(self) -> str:
        """Hash of the text as exported -- what a wiki importing this dump will
        recompute and store."""
        return content_sha1_base36(self.text)

    @property
    def sha1_is_self_consistent(self) -> bool:
        return self.declared_sha1 == self.content_sha1


@dataclass(frozen=True)
class DumpPage:
    title: str
    namespace: int
    revisions: tuple[DumpRevision, ...]  # oldest first, as exported

    @property
    def latest(self) -> DumpRevision:
        return self.revisions[-1]


def read_dump(path: Path | str) -> dict[str, DumpPage]:
    """Parse an export file into ``{title: DumpPage}``."""
    return _pages(ElementTree.parse(Path(path)).getroot())


def read_dump_text(xml: str) -> dict[str, DumpPage]:
    """Parse an XML export already captured in memory."""
    return _pages(ElementTree.fromstring(xml))


def _pages(root: ElementTree.Element) -> dict[str, DumpPage]:
    pages: dict[str, DumpPage] = {}
    for page_el in root.findall("{*}page"):
        title = _text(page_el, "{*}title") or ""
        revisions = tuple(
            _revision(rev_el) for rev_el in page_el.findall("{*}revision")
        )
        pages[title] = DumpPage(
            title=title,
            namespace=int(_text(page_el, "{*}ns") or 0),
            revisions=revisions,
        )
    return pages


def scan_dump(name: str) -> dict[str, DumpPage]:
    """Read one of the checked-in fixtures by filename."""
    return read_dump(SCANS_DIR / name)


def _revision(rev_el: ElementTree.Element) -> DumpRevision:
    contributor = rev_el.find("{*}contributor")
    user = _text(contributor, "{*}username") if contributor is not None else None
    byte_count = rev_el.find("{*}text").get("bytes")
    return DumpRevision(
        revid=int(_text(rev_el, "{*}id") or 0),
        timestamp=_text(rev_el, "{*}timestamp") or "",
        user=user,
        comment=_text(rev_el, "{*}comment"),
        declared_sha1=_text(rev_el, "{*}sha1"),
        # ElementTree has already decoded XML entities; this is the raw
        # wikitext the source wiki serves for the revision.
        text=_text(rev_el, "{*}text") or "",
        bytes=byte_count,
    )


def _text(element: ElementTree.Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path)
    return None if found is None else (found.text or "")
