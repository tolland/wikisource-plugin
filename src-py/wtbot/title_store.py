import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, col, select

from wtbot.model import Page, Title

"""Reading and writing titles: addresses we know about, fetched or not.

[Entry] is the unit most readers want: a title, and the page behind it if the
wiki holds one (step 3 of the split: a Page row exists only then).

Two operations:

- [ensure_title] -- the Title at an address, created with the caller's guess
  at its content model if we have not seen the address before. Callers that
  know better than a fallback (the index fan-out, the fetch) use this before
  creating a Page, so the guess on record is theirs rather than the transition
  hook's.
- [record_fetched_content_model] -- the fetch's check of that guess. The wiki
  has now said what the page is; a guess that disagreed is logged, because
  anything attached on the strength of it (``ProofreadPageMeta`` on a title
  that turns out to be wikitext) is now attached to the wrong kind of thing,
  and then corrected so the two do not disagree forever.
"""

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Entry:
    """What the cache holds at one title: the Title, and its Page if the wiki
    holds one."""

    title: Title
    page: Page | None

    @property
    def pk(self) -> int:
        assert self.title.pk is not None
        return self.title.pk

    @property
    def name(self) -> str:
        return self.title.title

    @property
    def content_model(self) -> str:
        return self.title.expected_content_model

    @property
    def pageid(self) -> int | None:
        return self.page.pageid if self.page is not None else None

    @property
    def revid(self) -> int | None:
        return self.page.revid if self.page is not None else None

    @property
    def timestamp(self) -> datetime | None:
        """Local save time over remote time: what the client's VirtualFile
        stamps."""
        remote = self.page.remote_timestamp if self.page is not None else None
        return self.title.local_modified_at or remote


def entry_at(session: Session, *, site_pk: int, title: str) -> Entry | None:
    """The Entry at (site, title), if we know the address at all."""
    row = session.exec(
        select(Title, Page)
        .outerjoin(Page, col(Page.pk) == col(Title.pk))
        .where(Title.site_pk == site_pk, Title.title == title)
    ).first()
    return None if row is None else Entry(*row)


def entry_by_pk(session: Session, pk: int) -> Entry | None:
    title = session.get(Title, pk)
    return None if title is None else Entry(title, session.get(Page, pk))


def ensure_title(
    session: Session, *, site_pk: int, title: str, expected_content_model: str
) -> Title:
    """The Title at (site, title), created with this guess if missing.

    An existing Title keeps its guess: the first caller to name an address
    decides what it is expected to be, and only a fetch overrides that.
    """
    existing = session.exec(
        select(Title).where(Title.site_pk == site_pk, Title.title == title)
    ).first()
    if existing is not None:
        return existing
    row = Title(
        site_pk=site_pk, title=title, expected_content_model=expected_content_model
    )
    session.add(row)
    session.flush()
    return row


def record_fetched_content_model(session: Session, row: Title, fetched: str) -> None:
    """Check the guess against what the wiki said, and adopt the wiki's answer."""
    if row.expected_content_model == fetched:
        return
    log.warning(
        "content model guess was wrong for %r (site %s): expected %r, the wiki "
        "says %r; anything attached on the strength of the guess may now be "
        "attached to the wrong kind of page",
        row.title,
        row.site_pk,
        row.expected_content_model,
        fetched,
    )
    row.expected_content_model = fetched
    session.add(row)
