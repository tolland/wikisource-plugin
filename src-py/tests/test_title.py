import logging

import pytest
from sqlmodel import Session, select

from wtbot.fetch.worker import run_pending
from wtbot.model import (
    BoxRangeLink,
    Commit,
    EditJournal,
    FetchRequest,
    Page,
    ProofreadPageMeta,
    ScanAnnotation,
    Site,
    TextTargetAnchor,
    Title,
)
from wtbot.page_processors import _ensure_placeholder_page, ensure_index_page
from wtbot.title_store import ensure_title, record_fetched_content_model
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

"""Step 1 of the Title/WikiPage split: every Page is a Title, sharing its pk.

These pin the transition rules rather than any behaviour built on Title yet --
nothing reads it except the fetch-time content-model check.
"""


@pytest.fixture
def site(session: Session) -> Site:
    row = Site(family="wikisource", code="en", label="en")
    session.add(row)
    session.commit()
    return row


def _title_at(session: Session, site: Site, title: str) -> Title:
    return session.exec(
        select(Title).where(Title.site_pk == site.pk, Title.title == title)
    ).one()


def test_a_page_created_without_a_pk_gets_its_title(session, site):
    page = Page(site_pk=site.pk, title="Main Page", content_model="wikitext")
    session.add(page)
    session.commit()

    title = _title_at(session, site, "Main Page")
    assert page.pk == title.pk
    assert title.expected_content_model == "wikitext"


def test_a_page_with_no_model_is_expected_to_be_wikitext(session, site):
    """MediaWiki's own fallback. A namespace does not decide it."""
    session.add(Page(site_pk=site.pk, title="Index:Book.pdf/styles.css"))
    session.commit()

    title = _title_at(session, site, "Index:Book.pdf/styles.css")
    assert title.expected_content_model == "wikitext"


def test_a_page_reuses_a_title_already_at_its_address(session, site):
    title = ensure_title(
        session,
        site_pk=site.pk,
        title="Page:Book.djvu/1",
        expected_content_model="proofread-page",
    )
    page = Page(site_pk=site.pk, title="Page:Book.djvu/1")
    session.add(page)
    session.commit()

    assert page.pk == title.pk
    assert len(session.exec(select(Title)).all()) == 1


def test_an_explicit_pk_names_the_title_too(session, site):
    page = Page(pk=4242, site_pk=site.pk, title="Index:Book.djvu")
    session.add(page)
    session.commit()

    assert _title_at(session, site, "Index:Book.djvu").pk == 4242


def test_an_explicit_pk_may_not_contradict_the_title_at_its_address(session, site):
    existing = ensure_title(
        session,
        site_pk=site.pk,
        title="Index:Book.djvu",
        expected_content_model="proofread-index",
    )
    session.commit()
    session.add(Page(pk=existing.pk + 100, site_pk=site.pk, title="Index:Book.djvu"))

    with pytest.raises(ValueError, match="already has pk"):
        session.flush()


def test_the_first_guess_stands_until_a_fetch(session, site):
    first = ensure_title(
        session, site_pk=site.pk, title="X", expected_content_model="proofread-page"
    )
    again = ensure_title(
        session, site_pk=site.pk, title="X", expected_content_model="wikitext"
    )

    assert again.pk == first.pk
    assert again.expected_content_model == "proofread-page"


def test_a_fetch_that_confirms_the_guess_is_silent(session, site, caplog):
    row = ensure_title(
        session, site_pk=site.pk, title="X", expected_content_model="wikitext"
    )
    with caplog.at_level(logging.WARNING, logger="wtbot.title_store"):
        record_fetched_content_model(session, row, "wikitext")

    assert caplog.records == []


def test_a_fetch_that_contradicts_the_guess_warns_and_corrects_it(
    session, site, caplog
):
    """Index:Foo.pdf/styles.css is in the Index namespace and is CSS: exactly
    the case a context guess gets wrong, and the fetch has to set right."""
    row = ensure_title(
        session,
        site_pk=site.pk,
        title="Index:Book.pdf/styles.css",
        expected_content_model="proofread-index",
    )
    with caplog.at_level(logging.WARNING, logger="wtbot.title_store"):
        record_fetched_content_model(session, row, "sanitized-css")

    assert row.expected_content_model == "sanitized-css"
    [record] = caplog.records
    assert "'proofread-index'" in record.getMessage()
    assert "'sanitized-css'" in record.getMessage()


def test_the_fan_out_records_its_own_guesses(session, site):
    """The fan-out knows more than the hook's fallback: its children are
    proofread pages and their owner is an index, before either is fetched."""
    _ensure_placeholder_page(
        session,
        site_pk=site.pk,
        index_title="Index:Book.djvu",
        title="Page:Book.djvu/3",
        page_number=3,
    )
    session.commit()

    page_title = _title_at(session, site, "Page:Book.djvu/3")
    index_title = _title_at(session, site, "Index:Book.djvu")
    assert page_title.expected_content_model == "proofread-page"
    assert index_title.expected_content_model == "proofread-index"
    assert session.get(Page, page_title.pk) is not None
    assert ensure_index_page(session, site.pk, "Index:Book.djvu").pk == index_title.pk


def _css_subpage() -> RemotePage:
    return RemotePage(
        title="Index:Book.pdf/styles.css",
        namespace_key=252,
        namespace_canonical="Index",
        content_model="sanitized-css",
        text=".x { color: red }",
        pageid=501,
        revid=9001,
    )


def _fetch(session: Session, site: Site, remote: RemotePage) -> None:
    session.add(FetchRequest(site_pk=site.pk, title=remote.title))
    session.commit()
    wiki = FakeWikiClient(pages={remote.title: remote})
    assert run_pending(session, lambda _: wiki) == 1


def test_a_first_fetch_records_the_wikis_answer_as_the_expectation(
    session, site, caplog
):
    remote = _css_subpage()
    with caplog.at_level(logging.WARNING, logger="wtbot.title_store"):
        _fetch(session, site, remote)

    title = _title_at(session, site, remote.title)
    assert title.expected_content_model == "sanitized-css"
    assert session.get(Page, title.pk).title == remote.title
    assert caplog.records == []


def test_the_fetch_worker_corrects_a_wrong_guess(session, site, caplog):
    """A title named in an Index namespace, guessed as an index before anyone
    looked, and fetched as CSS."""
    remote = _css_subpage()
    ensure_title(
        session,
        site_pk=site.pk,
        title=remote.title,
        expected_content_model="proofread-index",
    )
    session.commit()

    with caplog.at_level(logging.WARNING, logger="wtbot.title_store"):
        _fetch(session, site, remote)

    title = _title_at(session, site, remote.title)
    assert title.expected_content_model == "sanitized-css"
    assert session.get(Page, title.pk).content_model == "sanitized-css"
    assert any("'sanitized-css'" in r.getMessage() for r in caplog.records)


def test_saves_commits_and_meta_can_hang_off_a_bare_title(session, site):
    """Step 2: these three are about an address, so they key to a Title and
    need no Page behind it -- neither for the page itself nor for its index.
    Before, their foreign keys pointed at page.pk and refused this."""
    index = ensure_title(
        session,
        site_pk=site.pk,
        title="Index:Unfetched.djvu",
        expected_content_model="proofread-index",
    )
    leaf = ensure_title(
        session,
        site_pk=site.pk,
        title="Page:Unfetched.djvu/4",
        expected_content_model="proofread-page",
    )
    session.add(ProofreadPageMeta(title_pk=leaf.pk, index_title_pk=index.pk))
    session.add(EditJournal(title_pk=leaf.pk, body="first transcription"))
    session.add(Commit(title_pk=leaf.pk, submitted_body="first transcription"))
    session.commit()

    assert session.get(Page, leaf.pk) is None
    assert session.get(Page, index.pk) is None
    assert session.get(ProofreadPageMeta, leaf.pk).index_title_pk == index.pk


def test_annotations_can_be_drawn_on_a_bare_title(session, site):
    """The scan exists before the page does -- ProofreadPage serves it for an
    untranscribed page -- so marking it up needs a Title, not a Page."""
    leaf = ensure_title(
        session,
        site_pk=site.pk,
        title="Page:Unfetched.djvu/5",
        expected_content_model="proofread-page",
    )
    session.add(
        ScanAnnotation(
            title_pk=leaf.pk,
            annotation_id="box-1",
            normalized_x=0.1,
            normalized_y=0.1,
            normalized_width=0.2,
            normalized_height=0.2,
        )
    )
    session.add(
        TextTargetAnchor(
            title_pk=leaf.pk, annotation_id="range-1", text_start=0, text_end=5
        )
    )
    session.add(
        BoxRangeLink(
            title_pk=leaf.pk, box_annotation_id="box-1", range_annotation_id="range-1"
        )
    )
    session.commit()

    assert session.get(Page, leaf.pk) is None
