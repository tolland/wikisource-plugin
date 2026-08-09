from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.model import (
    FetchState,
    FileBlob,
    NsRole,
    Page,
    PageLink,
    PageMeta,
    RemoteLink,
    Site,
    SiteCredential,
)
from wtbot.revision_store import record_head_revision
from wtbot.wiki.wiki_types import RemotePage

"""``sync --from Index:X [--to Index:Y]``: the report before any push.

The case that matters most is the one with the least to compare: a work that
exists on one side and not the other. There is no pairing to key on, no anchor
to measure from, and every page is a create -- and that is a *report*, not an
error, because seeding a work from upstream is a thing people do.

Three things this pins:

- **the scan check runs first and its result is always on the response.** "We
  checked and they match" and "we could not check" are different claims, and a
  report that showed only the page list would conflate them. A mismatch blocks:
  different uploads mean page N on one side is not page N on the other, and
  every verdict below is off by an unknown offset.
- **placeholders are creates, not unknowns.** A row with no revision and
  `fetch_status=done` is a slot ProofreadPage paginates that nobody has
  transcribed -- we asked, and the answer was "absent". A row we simply have
  not fetched is a different state and gets a different verdict.
- **nothing is written.** Not to either wiki, and not to the local model: a
  report that created pairings as a side effect of being asked a question would
  make "just show me" the most consequential button on the page.
"""

SOURCE_INDEX = "Index:Varieties.djvu"
TARGET_INDEX = "Index:Varieties (local).djvu"
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
SCAN_SHA1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def body(level: int, user: str, words: str) -> str:
    return (
        f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>'
        f"{words}<noinclude></noinclude>"
    )


def build_site(session: Session, label: str) -> Site:
    site = Site(family=label, code="en", label=label)
    session.add(site)
    session.commit()
    session.refresh(site)
    session.add(SiteCredential(site_pk=site.pk, username="Admin", password="x"))
    session.commit()
    return site


def build_index(session: Session, site: Site, title: str, *, sha1: str | None) -> Page:
    page = Page(
        site_pk=site.pk,
        title=title,
        namespace_role=NsRole.index,
        content_model="proofread-index",
        revid=1,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    if sha1 is not None:
        _, _, basename = title.partition(":")
        file_page = Page(
            site_pk=site.pk, title=f"File:{basename}", namespace_role=NsRole.file
        )
        session.add(file_page)
        session.commit()
        session.refresh(file_page)
        session.add(FileBlob(page_pk=file_page.pk, file_sha1=sha1, page_count=3))
        session.commit()
    return page


def build_page(
    session: Session,
    site: Site,
    index_title: str,
    number: int,
    *,
    text: str | None,
    revid: int | None = None,
    title: str | None = None,
    fetched: bool = True,
) -> Page:
    """One Page: of a work.

    ``text=None`` builds a **placeholder** -- the stub an index fan-out writes
    for a paginated slot nobody has transcribed. ``fetched=False`` makes it the
    other kind of revision-less row: one we have simply not got to.
    """
    title = title or f"Page:Varieties.djvu/{number}"
    page = Page(
        site_pk=site.pk,
        title=title,
        namespace_role=NsRole.page,
        content_model="proofread-page",
        fetch_status=FetchState.done if fetched else FetchState.unfetched,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    session.add(PageMeta(page_pk=page.pk, index_title=index_title, page_number=number))
    session.commit()
    if text is not None:
        record_head_revision(
            session,
            page,
            RemotePage(
                title=title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=text,
                revid=revid,
                timestamp=WHEN,
            ),
        )
        session.commit()
    return page


def seed_source_only(engine, *, pages: int = 3) -> None:
    """The motivating case: a work upstream, nothing locally."""
    with Session(engine) as session:
        upstream = build_site(session, "wikisource")
        build_site(session, "mywikisource")
        build_index(session, upstream, SOURCE_INDEX, sha1=SCAN_SHA1)
        for number in range(1, pages + 1):
            build_page(
                session,
                upstream,
                SOURCE_INDEX,
                number,
                text=body(3, "Them", f"Page {number}."),
                revid=900 + number,
            )


def request(**overrides) -> dict:
    return {
        "source_label": "wikisource",
        "target_label": "mywikisource",
        "index_title": SOURCE_INDEX,
        **overrides,
    }


# -- the motivating case ------------------------------------------------------


def test_a_work_absent_on_the_target_reports_every_page_as_a_create(client, engine):
    seed_source_only(engine)

    report = client.post("/sync/report", json=request())
    assert report.status_code == 200, report.text
    data = report.json()

    assert data["source"]["exists"] is True
    assert data["target"]["exists"] is False
    assert data["counts"] == {"create": 3}
    assert data["actionable"] == 3
    assert all(page["target_title"] is None for page in data["pages"])


def test_the_absent_target_index_is_a_blocker_not_an_error(client, engine):
    """Reported alongside the work rather than instead of it: seeding a work
    from upstream is a thing people do, and the page list is what they came
    for."""
    seed_source_only(engine)
    data = client.post("/sync/report", json=request()).json()

    assert data["blocked"] is True
    assert any("does not exist" in blocker for blocker in data["blockers"])
    assert len(data["pages"]) == 3


def test_an_uncached_source_index_is_a_404_that_says_what_to_do(client, engine):
    with Session(engine) as session:
        build_site(session, "wikisource")
        build_site(session, "mywikisource")

    missing = client.post("/sync/report", json=request())
    assert missing.status_code == 404
    assert "fetch the source index first" in missing.json()["detail"].lower()


# -- the scan check -----------------------------------------------------------


def test_differing_backing_scans_block_the_whole_work(client, engine):
    """Discussion section 6: different uploads mean page N on one side is not
    page N on the other, and every verdict below is off by an unknown offset."""
    seed_source_only(engine)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1="b" * 40)

    data = client.post("/sync/report", json=request()).json()

    assert data["scan"]["status"] == "mismatch"
    assert data["scan"]["blocks"] is True
    assert data["blocked"] is True
    assert data["scan"]["source_sha1"] != data["scan"]["target_sha1"]


def test_the_same_upload_passes_the_scan_check(client, engine):
    seed_source_only(engine)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)

    data = client.post("/sync/report", json=request()).json()

    assert data["scan"]["status"] == "ok"
    assert data["blocked"] is False


def test_a_target_without_a_file_is_unverifiable_rather_than_blocked(client, engine):
    """An Index: without a File: is legal, so this is not a refusal -- but
    nothing then validates the page correspondence, and the report says so
    rather than implying a check happened."""
    seed_source_only(engine)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=None)

    data = client.post("/sync/report", json=request()).json()

    assert data["scan"]["status"] == "unverifiable"
    assert data["scan"]["blocks"] is False
    assert data["blocked"] is False
    assert "rests on page numbers" in data["scan"]["detail"]


# -- placeholders -------------------------------------------------------------


def test_a_placeholder_target_page_is_a_create(client, engine):
    """A slot the index paginates that nobody has transcribed. We asked the
    wiki and the answer was 'absent' -- that is work to do, not a gap in what
    we know."""
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(session, local, SOURCE_INDEX, 1, text=None)

    data = client.post("/sync/report", json=request()).json()

    (page,) = data["pages"]
    assert page["verdict"] == "create"
    assert page["target_is_placeholder"] is True
    assert page["target_title"] is not None  # the row exists, the revision does not
    assert "never transcribed" in page["detail"]


def test_an_unfetched_target_page_is_unknown_not_a_create(client, engine):
    """The distinction the placeholder flag exists for: a row we have not got
    to says nothing about whether the page exists on the wiki, and writing it
    as a create could clobber a page somebody else wrote."""
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(session, local, SOURCE_INDEX, 1, text=None, fetched=False)

    (page,) = client.post("/sync/report", json=request()).json()["pages"]
    assert page["verdict"] == "unknown"
    assert page["target_is_placeholder"] is False
    assert page["actionable"] is False


def test_placeholders_are_counted_on_the_side_summary(client, engine):
    seed_source_only(engine, pages=2)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(session, local, SOURCE_INDEX, 1, text=None)
        build_page(
            session, local, SOURCE_INDEX, 2, text=body(3, "Us", "Page 2."), revid=5
        )

    target = client.post("/sync/report", json=request()).json()["target"]
    assert target["cached_pages"] == 2
    assert target["placeholder_pages"] == 1


# -- the directional verdicts -------------------------------------------------


def test_a_converged_work_is_in_sync(client, engine):
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        # Same transcription, different attribution -- the cross-site norm.
        build_page(
            session, local, SOURCE_INDEX, 1, text=body(3, "Us", "Page 1."), revid=5
        )

    data = client.post("/sync/report", json=request()).json()
    assert data["counts"] == {"in_sync": 1}
    assert data["actionable"] == 0


def test_the_direction_decides_push_from_pull(client, engine):
    """The whole reason this has its own vocabulary. The pair is the same pair;
    which side is the source is what makes it a push or a pull."""
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        page = build_page(
            session, local, SOURCE_INDEX, 1, text=body(3, "Us", "Page 1."), revid=5
        )
        # The upstream side then edits: it is one revision ahead of the anchor.
        upstream_page = session.exec(
            select(Page).where(
                Page.title == "Page:Varieties.djvu/1", Page.pk != page.pk
            )
        ).one()
        record_head_revision(
            session,
            upstream_page,
            RemotePage(
                title=upstream_page.title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=body(3, "Them", "Page 1 revised."),
                revid=999,
                parentid=901,
                timestamp=WHEN,
            ),
        )
        session.commit()

    forward = client.post("/sync/report", json=request()).json()
    (page_row,) = forward["pages"]
    assert page_row["verdict"] == "push"
    assert page_row["source_ahead_by"] == 1

    reversed_ = client.post(
        "/sync/report",
        json=request(
            source_label="mywikisource",
            target_label="wikisource",
            index_title=SOURCE_INDEX,
        ),
    ).json()
    (reversed_row,) = reversed_["pages"]
    assert reversed_row["verdict"] == "pull"
    assert reversed_row["target_ahead_by"] == 1
    # Same pair, opposite direction: the push is only actionable one way round.
    assert page_row["actionable"] is True
    assert reversed_row["actionable"] is False


def test_a_page_only_on_the_target_is_surfaced(client, engine):
    """A work that grew on the other side is exactly what a sync should show;
    silence would look like agreement."""
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(
            session, local, SOURCE_INDEX, 1, text=body(3, "Us", "Page 1."), revid=5
        )
        build_page(
            session, local, SOURCE_INDEX, 2, text=body(3, "Us", "Page 2."), revid=6
        )

    data = client.post("/sync/report", json=request()).json()
    verdicts = {row["page_number"]: row["verdict"] for row in data["pages"]}
    assert verdicts == {1: "in_sync", 2: "source_missing"}


def test_an_index_title_that_differs_is_addressed_with_to(client, engine):
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, TARGET_INDEX, sha1=SCAN_SHA1)
        build_page(
            session,
            local,
            TARGET_INDEX,
            1,
            text=body(3, "Us", "Page 1."),
            revid=5,
            title="Page:Varieties (local).djvu/1",
        )

    data = client.post(
        "/sync/report", json=request(target_index_title=TARGET_INDEX)
    ).json()

    assert data["target"]["exists"] is True
    (page,) = data["pages"]
    assert page["verdict"] == "in_sync"
    assert page["target_title"] == "Page:Varieties (local).djvu/1"


def test_the_report_is_ordered_for_reading(client, engine):
    seed_source_only(engine, pages=3)
    numbers = [
        row["page_number"]
        for row in client.post("/sync/report", json=request()).json()["pages"]
    ]
    assert numbers == [1, 2, 3]


# -- and it writes nothing ----------------------------------------------------


def test_the_report_writes_nothing_to_the_local_model(client, engine):
    """Not even the pairings it reads. A report that paired pages as a side
    effect of being asked a question would be the most consequential button on
    the page."""
    seed_source_only(engine, pages=2)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(
            session, local, SOURCE_INDEX, 1, text=body(3, "Us", "Page 1."), revid=5
        )

    for _ in range(2):
        client.post("/sync/report", json=request())

    with Session(engine) as session:
        assert session.exec(select(PageLink)).all() == []
        assert session.exec(select(RemoteLink)).all() == []


def test_a_tracked_work_is_named_on_the_report(client, engine):
    """So the viewer can offer the drill-down instead of re-deriving it."""
    seed_source_only(engine, pages=1)
    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        build_index(session, local, SOURCE_INDEX, sha1=SCAN_SHA1)
        build_page(
            session, local, SOURCE_INDEX, 1, text=body(3, "Us", "Page 1."), revid=5
        )

    tracked = client.post(
        "/links/works",
        json={
            "local_label": "wikisource",
            "remote_label": "mywikisource",
            "index_title": SOURCE_INDEX,
        },
    )
    assert tracked.status_code == 201, tracked.text

    data = client.post("/sync/report", json=request()).json()
    assert data["work_pk"] == tracked.json()["work"]["pk"]
