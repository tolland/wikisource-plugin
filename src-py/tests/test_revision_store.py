from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.model import (
    MAIN_SLOT,
    Content,
    FetchRequest,
    Page,
    Revision,
    Site,
    Slot,
)
from wtbot.revision_store import record_head_revision, upsert_content
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.sha1 import content_sha1_base36, hex_to_base36
from wtbot.wiki.wiki_types import RemotePage
from wtbot.worker import run_pending

"""The page -> revision -> slot -> content chain the fetch worker writes.

The property that matters: content is addressed by *our* hash of the bytes the
API served, so identical text collapses to one row across revisions and across
sites. That is what turns cross-wiki "is this the same content?" into a join.
"""

PROOFREAD = "proofread-page"


def _site(session: Session, *, family: str, code: str = "en") -> Site:
    site = Site(family=family, code=code)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def _page(session: Session, site: Site, title: str) -> Page:
    page = Page(site_pk=site.pk, title=title)
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def _remote(text: str, *, revid: int, sha1: str | None = None, **kw) -> RemotePage:
    return RemotePage(
        title=kw.pop("title", "Page:Work.djvu/1"),
        namespace_key=104,
        namespace_canonical="Page",
        content_model=kw.pop("content_model", PROOFREAD),
        text=text,
        revid=revid,
        sha1=sha1,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        **kw,
    )


def test_content_is_addressed_by_our_hash(session: Session) -> None:
    content = upsert_content(session, "some body", content_model=PROOFREAD)

    assert content.content_sha1 == content_sha1_base36("some body")
    assert content.size == len("some body".encode())
    assert len(content.content_sha1) == 31


def test_identical_text_dedupes_to_one_row(session: Session) -> None:
    first = upsert_content(session, "shared body", content_model=PROOFREAD)
    second = upsert_content(session, "shared body", content_model=PROOFREAD)

    assert first.pk == second.pk
    assert len(session.exec(select(Content)).all()) == 1


def test_same_text_under_a_different_model_is_a_separate_row(
    session: Session,
) -> None:
    """Identical bytes under two content models are not interchangeable."""
    a = upsert_content(session, "same bytes", content_model=PROOFREAD)
    b = upsert_content(session, "same bytes", content_model="wikitext")

    assert a.pk != b.pk
    assert a.content_sha1 == b.content_sha1


def test_content_dedupes_across_sites(session: Session) -> None:
    """The join that makes cross-wiki correspondence checkable rather than
    asserted: two pages on two different wikis holding the same text resolve to
    one Content row."""
    upstream = _site(session, family="wikisource")
    local = _site(session, family="mywikisource")
    up_page = _page(session, upstream, "Page:Work.djvu/1")
    local_page = _page(session, local, "Page:Work.djvu/1")

    body = '<noinclude><pagequality level="3" user="A" /></noinclude>Text.'
    record_head_revision(session, up_page, _remote(body, revid=10))
    record_head_revision(session, local_page, _remote(body, revid=77))
    session.commit()

    assert len(session.exec(select(Content)).all()) == 1
    assert len(session.exec(select(Revision)).all()) == 2

    slots = session.exec(select(Slot)).all()
    assert len({slot.content_pk for slot in slots}) == 1


def test_head_revision_is_recorded_with_a_main_slot(session: Session) -> None:
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    revision = record_head_revision(session, page, _remote("body", revid=42))
    session.commit()

    assert revision is not None
    assert revision.revid == 42
    assert page.latest_revision_pk == revision.pk

    slot = session.get(Slot, (revision.pk, MAIN_SLOT))
    assert slot is not None
    content = session.get(Content, slot.content_pk)
    assert content.text == "body"


def test_remote_hash_is_normalised_and_kept_separate(session: Session) -> None:
    """The wiki's hash rides along in base-36 but never becomes the identity.

    For proofread-page the two legitimately differ -- the wiki hashes the bytes
    it stored, we hash the bytes it served.
    """
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")
    # A hex digest of *different* bytes, as the API would report it.
    remote_hex = "61ad96427deee611bb5bac3b8fa3318ceb46e06f"

    revision = record_head_revision(
        session, page, _remote("served body", revid=7, sha1=remote_hex)
    )
    session.commit()

    slot = session.get(Slot, (revision.pk, MAIN_SLOT))
    content = session.get(Content, slot.content_pk)

    assert content.remote_sha1 == hex_to_base36(remote_hex)
    assert content.content_sha1 == content_sha1_base36("served body")
    assert content.sha1_agrees is False
    assert revision.remote_sha1 == hex_to_base36(remote_hex)


def test_sha1_agrees_when_stored_and_served_coincide(session: Session) -> None:
    """The verified-shortcut case: wikitext stores what it serves, so the
    wiki's hash corroborates ours and can be trusted for that row."""
    site = _site(session, family="wikisource")
    page = _page(session, site, "Project:Plain")
    body = "plain wikitext\n"
    agreeing_hex = f"{int(content_sha1_base36(body), 36):040x}"

    revision = record_head_revision(
        session,
        page,
        _remote(body, revid=3, sha1=agreeing_hex, content_model="wikitext"),
    )
    session.commit()

    slot = session.get(Slot, (revision.pk, MAIN_SLOT))
    assert session.get(Content, slot.content_pk).sha1_agrees is True


def test_refetching_the_same_revision_is_idempotent(session: Session) -> None:
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    record_head_revision(session, page, _remote("body", revid=42))
    session.commit()
    record_head_revision(session, page, _remote("body", revid=42))
    session.commit()

    assert len(session.exec(select(Revision)).all()) == 1
    assert len(session.exec(select(Slot)).all()) == 1
    assert len(session.exec(select(Content)).all()) == 1


def test_a_new_revision_adds_a_row_and_moves_the_head(session: Session) -> None:
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    first = record_head_revision(session, page, _remote("v1", revid=1))
    session.commit()
    second = record_head_revision(session, page, _remote("v2", revid=2, parentid=1))
    session.commit()

    assert first.pk != second.pk
    assert page.latest_revision_pk == second.pk
    assert second.parent_revid == 1
    assert len(session.exec(select(Revision)).all()) == 2


def test_a_placeholder_records_no_revision(session: Session) -> None:
    """A page that does not exist remotely must not manufacture a revision --
    the same known-absent discipline placeholders already carry."""
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/9")

    assert record_head_revision(session, page, _remote("", revid=None)) is None
    session.commit()

    assert session.exec(select(Revision)).all() == []
    assert page.latest_revision_pk is None


def test_the_fetch_worker_populates_the_store(session: Session) -> None:
    """End to end through the real worker: a fetch must leave the revision
    chain behind it, and the Page head columns must still agree with it.

    The head columns stay the denormalisation every existing reader uses, so a
    divergence between them and the revision they summarise is a bug.
    """
    site = _site(session, family="wikisource")
    remote = _remote("fetched body", revid=99, title="Page:Fetched.djvu/1")
    wiki = FakeWikiClient(pages={remote.title: remote})

    session.add(FetchRequest(site_pk=site.pk, title=remote.title))
    session.commit()
    assert run_pending(session, lambda _: wiki) == 1

    page = session.exec(select(Page).where(Page.title == remote.title)).one()
    revision = session.exec(select(Revision).where(Revision.page_pk == page.pk)).one()

    assert page.latest_revision_pk == revision.pk
    assert revision.revid == page.revid == 99

    slot = session.get(Slot, (revision.pk, MAIN_SLOT))
    content = session.get(Content, slot.content_pk)
    assert content.text == page.text == "fetched body"
    assert content.content_sha1 == content_sha1_base36("fetched body")


def test_history_is_sparse_until_a_walk_says_otherwise(session: Session) -> None:
    """Recording heads never claims a contiguous range: a base search must not
    read "the oldest row we hold" as "where the histories diverge"."""
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    record_head_revision(session, page, _remote("v5", revid=5))
    session.commit()

    assert page.history_complete_from_revid is None
