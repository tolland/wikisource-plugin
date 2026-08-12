from datetime import datetime, timezone

import pytest
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
from wtbot.revision_store import (
    RemoteIdentityError,
    record_head_revision,
    upsert_content,
    validate_remote_identity,
)
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.sha1 import content_sha1_base36, hex_to_base36
from wtbot.wiki.wiki_types import RemotePage
from wtbot.worker import run_pending

"""The page -> revision -> slot -> content chain the fetch worker writes.

Content is addressed by *our* hash of the bytes the API served, so identical
text collapses to one row. Within a site that is a reliable identity. Across
sites it is only a storage convenience -- a proofread-page body embeds a
site-specific ``pagequality user=``, so equivalent transcriptions routinely hash
differently; correspondence is asserted via RemoteLink instead.
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
    """Identical bytes resolve to one row regardless of which site they came
    from.

    Useful for storage and for the cases where text really does match, but note
    it is *not* how cross-site correspondence is decided: a proofread-page body
    embeds a site-specific `pagequality user=`, so equivalent transcriptions
    routinely differ. Correspondence is asserted via RemoteLink.
    """
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
    # The revision carries no hash of its own: rev_sha1 is the main slot's
    # content_sha1, so storing it again would be a second name for one value.
    assert not hasattr(revision, "remote_sha1")


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


def test_a_revid_cannot_move_to_another_page_on_the_same_site(
    session: Session,
) -> None:
    """MediaWiki revids are site-global. Seeing one on a different page means
    this cache crossed a database restore/replacement boundary."""
    site = _site(session, family="wikisource")
    first = _page(session, site, "Page:Work.djvu/1")
    second = _page(session, site, "Page:Work.djvu/2")
    record_head_revision(
        session, first, _remote("one", revid=42, pageid=10, title=first.title)
    )
    session.commit()

    with pytest.raises(RemoteIdentityError, match="revid 42.*already cached"):
        record_head_revision(
            session,
            second,
            _remote("two", revid=42, pageid=11, title=second.title),
        )


def test_partial_snapshots_may_reuse_placeholder_revids_across_pages(
    session: Session,
) -> None:
    """A RemotePage without pageid is deliberately incomplete.

    Fake clients use such snapshots throughout focused tests, often with
    ``revid=1`` as incidental metadata. They must still record independently;
    production snapshots carry pageid and exercise the site-global check above.
    """
    site = _site(session, family="wikisource")
    first = _page(session, site, "Page:Work.djvu/1")
    second = _page(session, site, "Page:Work.djvu/2")

    record_head_revision(session, first, _remote("one", revid=1, title=first.title))
    record_head_revision(session, second, _remote("two", revid=1, title=second.title))
    session.commit()

    assert len(session.exec(select(Revision).where(Revision.revid == 1)).all()) == 2


def test_the_same_numeric_revid_is_allowed_on_different_sites(
    session: Session,
) -> None:
    local = _site(session, family="mywikisource")
    upstream = _site(session, family="wikisource")
    local_page = _page(session, local, "Page:Work.djvu/1")
    upstream_page = _page(session, upstream, "Page:Work.djvu/1")

    record_head_revision(session, local_page, _remote("local", revid=42))
    record_head_revision(session, upstream_page, _remote("upstream", revid=42))
    session.commit()

    assert len(session.exec(select(Revision).where(Revision.revid == 42)).all()) == 2


def test_an_existing_revid_cannot_change_content(session: Session) -> None:
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")
    record_head_revision(session, page, _remote("before", revid=42))
    session.commit()

    with pytest.raises(RemoteIdentityError, match="revid 42.*changed content"):
        record_head_revision(session, page, _remote("after", revid=42))


def test_a_title_cannot_silently_change_pageid(session: Session) -> None:
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")
    page.pageid = 10
    session.add(page)
    session.commit()

    with pytest.raises(RemoteIdentityError, match="changed pageid from 10 to 11"):
        validate_remote_identity(session, page, _remote("body", revid=42, pageid=11))


def test_a_pageid_cannot_name_two_titles_on_the_same_site(session: Session) -> None:
    site = _site(session, family="wikisource")
    first = _page(session, site, "Page:Work.djvu/1")
    second = _page(session, site, "Page:Work.djvu/2")
    first.pageid = 10
    session.add(first)
    session.commit()

    with pytest.raises(RemoteIdentityError, match="pageid 10.*already cached"):
        validate_remote_identity(
            session,
            second,
            _remote("body", revid=42, pageid=10, title=second.title),
        )


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


def test_a_head_with_an_unheld_parent_claims_no_contiguous_range(
    session: Session,
) -> None:
    """A base search must not read "the oldest row we hold" as "where the
    histories diverge". Recording a head whose parent we do not have says
    nothing about how far back we can see."""
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    record_head_revision(session, page, _remote("v5", revid=5, parentid=4))
    session.commit()

    assert page.history_complete_from_revid == 5
    # The marker names the oldest revision of the contiguous run, which here is
    # the head itself -- and that run does not reach the beginning, because
    # revision 4 exists and we do not hold it.
    head = session.exec(select(Revision).where(Revision.revid == 5)).one()
    assert head.parent_revid == 4


def test_a_head_with_no_parent_is_the_whole_history(session: Session) -> None:
    """The other half, and the one that matters for the anchor search: a
    revision with no parent is the page's first, so a page whose head has no
    parent has exactly one revision and we hold all of it.

    Left unmarked, every never-edited page would report "we did not look far
    enough back" when there is nowhere further to look -- which turns a real
    divergence into a fetch that can never help.
    """
    site = _site(session, family="wikisource")
    page = _page(session, site, "Page:Work.djvu/1")

    record_head_revision(session, page, _remote("only", revid=5))
    session.commit()

    assert page.history_complete_from_revid == 5
    head = session.exec(select(Revision).where(Revision.revid == 5)).one()
    assert head.parent_revid is None
