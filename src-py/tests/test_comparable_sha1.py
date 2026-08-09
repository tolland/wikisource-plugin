from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.content_model import ProofreadPageDocument, Significance, comparable_sha1
from wtbot.model import Content, NsRole, Page, Site
from wtbot.revision_store import record_head_revision, upsert_content
from wtbot.wiki.wiki_types import RemotePage

"""``Content.comparable_sha1``: the model-aware comparison, precomputed.

The property that has to hold, because the anchor search now decides on the
digest and only parses the revision it settled on:

    two digests are equal  <->  the comparison calls them the same content

where "the same content" is the predicate the search runs -- same transcription
at a significance other than ``metadata_significant``. Both directions matter
and they fail differently: a false match links two revisions that are not the
same, a false miss reports a synced page as diverged.
"""

BODY = (
    '<noinclude><pagequality level="3" user="Tolland" /></noinclude>{{c/s}}\n'
    "Some title\n"
    "{{c/e}}<noinclude></noinclude>"
)
OTHER_USER = BODY.replace('user="Tolland"', 'user="Other Side User"')
OTHER_LEVEL = BODY.replace('level="3"', 'level="4"')
OTHER_TEXT = BODY.replace("Some title", "Some other title")

MODEL = "proofread-page"


def _matches(left: str, right: str) -> bool:
    """The predicate the anchor search runs, computed the slow way."""
    comparison = ProofreadPageDocument.parse(left).compare(
        ProofreadPageDocument.parse(right)
    )
    return comparison.same_transcription and comparison.significance is not (
        Significance.metadata_significant
    )


def test_the_username_is_stripped_before_hashing() -> None:
    """The case the digest exists for: the same transcription attributed to an
    account on each wiki. `content_sha1` cannot see past it."""
    assert comparable_sha1(BODY, MODEL) == comparable_sha1(OTHER_USER, MODEL)
    assert _matches(BODY, OTHER_USER)


def test_the_proofreading_level_is_not_stripped() -> None:
    """Level is significant and directional -- equal words at level 3 and level
    4 are not interchangeable, so they must not share a digest."""
    assert comparable_sha1(BODY, MODEL) != comparable_sha1(OTHER_LEVEL, MODEL)
    assert not _matches(BODY, OTHER_LEVEL)


def test_different_transcriptions_hash_differently() -> None:
    assert comparable_sha1(BODY, MODEL) != comparable_sha1(OTHER_TEXT, MODEL)
    assert not _matches(BODY, OTHER_TEXT)


def test_an_absent_level_is_distinct_from_level_zero() -> None:
    """A body that never went through ProofreadPage is not a level-0 body, and
    joining the parts with an empty string would have made it one."""
    unmarked = "<noinclude></noinclude>Words<noinclude></noinclude>"
    zero = '<noinclude><pagequality level="0" user="X" /></noinclude>Words<noinclude></noinclude>'
    assert comparable_sha1(unmarked, MODEL) != comparable_sha1(zero, MODEL)


def test_the_parts_cannot_alias_across_the_split() -> None:
    """Header, body and footer are joined by a character wikitext cannot
    contain, so "footer moved into the body" is not the same digest."""
    split = "<noinclude>Head</noinclude>Body<noinclude>Foot</noinclude>"
    merged = "<noinclude></noinclude>HeadBodyFoot<noinclude></noinclude>"
    assert comparable_sha1(split, MODEL) != comparable_sha1(merged, MODEL)


def test_plain_wikitext_hashes_its_whole_body() -> None:
    """No embedded metadata, so the canonical form is the text -- with line
    endings normalised, which is the one difference that is never real."""
    assert comparable_sha1("a\r\nb", "wikitext") == comparable_sha1("a\nb", "wikitext")
    assert comparable_sha1("a\nb", "wikitext") != comparable_sha1("a\nc", "wikitext")


def test_the_digest_agrees_with_the_comparison_on_real_bodies() -> None:
    """The equivalence stated at the top of this module, over every pair of the
    four fixtures -- the thing that would silently break if the canonical form
    and the comparison ever drifted apart."""
    bodies = {
        "base": BODY,
        "other user": OTHER_USER,
        "other level": OTHER_LEVEL,
        "other text": OTHER_TEXT,
    }
    for left_name, left in bodies.items():
        for right_name, right in bodies.items():
            digests_agree = comparable_sha1(left, MODEL) == comparable_sha1(
                right, MODEL
            )
            assert digests_agree == _matches(
                left, right
            ), f"{left_name} vs {right_name}"


# -- storage ----------------------------------------------------------------


def test_the_store_writes_the_digest(session: Session) -> None:
    content = upsert_content(session, BODY, content_model=MODEL)
    assert content.comparable_sha1 == comparable_sha1(BODY, MODEL)
    # Distinct from the byte hash, which is what makes it worth its own column.
    assert content.comparable_sha1 != content.content_sha1


def test_the_store_fills_in_a_row_that_predates_the_column(session: Session) -> None:
    """An upsert that finds an existing row backfills it on the way past, so a
    database migrated by an older wtbot converges without a second pass."""
    first = upsert_content(session, BODY, content_model=MODEL)
    first.comparable_sha1 = None
    session.add(first)
    session.flush()

    again = upsert_content(session, BODY, content_model=MODEL)
    assert again.pk == first.pk
    assert again.comparable_sha1 == comparable_sha1(BODY, MODEL)


def test_two_sites_bodies_share_a_digest_but_not_a_row(session: Session) -> None:
    """The whole point in one assertion: the two wikis store different bytes --
    two `content` rows, two `content_sha1`s -- and the same transcription."""
    for family, body in (("mywikisource", BODY), ("wikisource", OTHER_USER)):
        site = Site(family=family, code="en", label=family)
        session.add(site)
        session.commit()
        session.refresh(site)
        page = Page(
            site_pk=site.pk, title="Page:Work.djvu/1", namespace_role=NsRole.page
        )
        session.add(page)
        session.commit()
        session.refresh(page)
        record_head_revision(
            session,
            page,
            RemotePage(
                title=page.title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model=MODEL,
                text=body,
                revid=7,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        session.commit()

    rows = session.exec(select(Content)).all()
    assert len({row.content_sha1 for row in rows}) == 2
    assert len({row.comparable_sha1 for row in rows}) == 1
