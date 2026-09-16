from datetime import datetime, timedelta, timezone

from conftest import credential_for, drain
from sqlmodel import Session, select

from wtbot.incremental import RefreshBasis, plan_refresh
from wtbot.model import FetchRequest, Namespace, NsRole, Page, Site
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemoteChange, RemotePage

"""Planning an incremental refresh.

The point is not that recentchanges is queried -- it is what happens when it
cannot answer. The table is pruned (``$wgRCMaxAge``, 90 days by default), so
past that horizon "nothing changed" and "the wiki no longer remembers" are the
same empty response, and the difference between them is every page that moved
while we were away.
"""

INDEX = "Index:Canadian patent 29537.djvu"
PAGE_NS = 104
INDEX_NS = 106

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
LABEL = "en.wikisource"


def _site(session: Session, **kwargs) -> Site:
    """A site with its Page:/Index: namespaces synced, as a fetch would leave
    them. The numbers are en.wikisource's; the point of the role lookup is that
    nothing depends on that."""
    site = Site(family="wikisource", code="en", label=LABEL, **kwargs)
    session.add(site)
    session.commit()
    session.refresh(site)
    credential_for(session, site)

    for key, role in ((PAGE_NS, NsRole.page), (INDEX_NS, NsRole.index)):
        session.add(
            Namespace(
                site_pk=site.pk,
                key=key,
                canonical_name=role.value.title(),
                local_name=role.value.title(),
                role=role,
            )
        )
    session.commit()
    return site


def _page(session: Session, site: Site, title: str) -> Page:
    page = Page(site_pk=site.pk, title=title)
    session.add(page)
    session.commit()
    return page


def _change(title: str, *, minutes: int, ns: int = PAGE_NS, kind: str = "edit"):
    return RemoteChange(
        title=title,
        timestamp=NOW + timedelta(minutes=minutes),
        kind=kind,
        namespace_key=ns,
        revid=1000 + minutes,
    )


def _work_page(number: int) -> str:
    return f"Page:Canadian patent 29537.djvu/{number}"


def test_only_the_titles_that_moved_are_planned(session: Session) -> None:
    site = _site(session)
    for number in (1, 2, 3):
        _page(session, site, _work_page(number))

    client = FakeWikiClient(changes=[_change(_work_page(2), minutes=5)])
    plan = plan_refresh(session, site, client, since=NOW)

    assert plan.basis is RefreshBasis.incremental
    assert plan.titles == (_work_page(2),)


def test_since_older_than_the_wiki_remembers_forces_a_full_pass(
    session: Session,
) -> None:
    """The failure this exists to prevent: recentchanges returning nothing
    because the window has been pruned, read as "nothing changed"."""
    site = _site(session)
    for number in (1, 2, 3):
        _page(session, site, _work_page(number))

    # The wiki's oldest surviving entry is far newer than our since timestamp: the
    # year in between has been pruned, so an empty-looking answer would be a
    # lie rather than good news.
    client = FakeWikiClient(
        changes=[_change(_work_page(2), minutes=5)], oldest_change=NOW
    )
    plan = plan_refresh(session, site, client, since=NOW - timedelta(days=365))

    assert plan.basis is RefreshBasis.full
    assert set(plan.titles) == {_work_page(n) for n in (1, 2, 3)}
    assert "predates" in plan.reason


def test_an_empty_change_stream_is_answerable(session: Session) -> None:
    """A wiki with no recentchanges at all cannot contradict our start timestamp, so
    "nothing moved" is the honest answer -- distinct from the pruned case."""
    site = _site(session)
    _page(session, site, _work_page(1))

    plan = plan_refresh(session, site, FakeWikiClient(changes=[]), since=NOW)

    assert plan.basis is RefreshBasis.incremental
    assert plan.titles == ()


def test_changes_to_pages_we_do_not_hold_are_ignored(session: Session) -> None:
    """Without a prefix there is nothing to say a strange title belongs to a
    work we track, so the scan stays within what we hold."""
    site = _site(session)
    _page(session, site, _work_page(1))

    client = FakeWikiClient(
        changes=[
            _change(_work_page(1), minutes=1),
            _change("Page:Something else.djvu/1", minutes=2),
        ]
    )
    plan = plan_refresh(session, site, client, since=NOW)

    assert plan.titles == (_work_page(1),)


def test_a_prefix_scan_picks_up_pages_created_since(session: Session) -> None:
    """The discovery case: a partially transcribed index grows new Page:
    subpages, and nothing local matches them yet."""
    site = _site(session)
    _page(session, site, _work_page(1))

    client = FakeWikiClient(
        changes=[
            _change(_work_page(9), minutes=3, kind="new"),
            _change("Page:Unrelated.djvu/1", minutes=4, kind="new"),
        ]
    )
    plan = plan_refresh(
        session,
        site,
        client,
        since=NOW,
        title_prefix="Page:Canadian patent 29537.djvu/",
    )

    assert plan.titles == (_work_page(9),)


def test_one_title_edited_twice_is_fetched_once(session: Session) -> None:
    site = _site(session)
    _page(session, site, _work_page(1))

    client = FakeWikiClient(
        changes=[_change(_work_page(1), minutes=1), _change(_work_page(1), minutes=2)]
    )
    plan = plan_refresh(session, site, client, since=NOW)

    assert plan.titles == (_work_page(1),)
    assert len(plan.changes) == 2


def test_namespaces_are_filtered_by_role_not_by_number(session: Session) -> None:
    """Page:/Index: ids differ between installs, so the server-side filter is
    resolved from this site's rows."""
    site = _site(session)
    _page(session, site, _work_page(1))

    seen: dict = {}

    class RecordingClient(FakeWikiClient):
        def recent_changes(self, *, since, namespace_keys=None, limit=5000):
            seen["namespace_keys"] = namespace_keys
            return super().recent_changes(
                since=since, namespace_keys=namespace_keys, limit=limit
            )

    plan_refresh(session, site, RecordingClient(changes=[]), since=NOW)

    assert seen["namespace_keys"] == [PAGE_NS, INDEX_NS]


def test_an_unsynced_namespace_table_does_not_filter_everything_out(
    session: Session,
) -> None:
    """An empty rcnamespace matches nothing, which would look exactly like a
    wiki where nothing ever changes."""
    site = Site(family="wikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    _page(session, site, _work_page(1))

    seen: dict = {}

    class RecordingClient(FakeWikiClient):
        def recent_changes(self, *, since, namespace_keys=None, limit=5000):
            seen["namespace_keys"] = namespace_keys
            return super().recent_changes(
                since=since, namespace_keys=namespace_keys, limit=limit
            )

    plan_refresh(
        session,
        site,
        RecordingClient(changes=[_change(_work_page(1), minutes=1)]),
        since=NOW,
    )

    assert seen["namespace_keys"] is None


def test_refresh_endpoint_fetches_only_what_moved(client, engine) -> None:
    """End to end through the API: a refresh enqueues the changed title into
    the ordinary fetch path."""
    moved = _work_page(2)
    remote = RemotePage(
        title=moved,
        namespace_key=PAGE_NS,
        namespace_canonical="Page",
        content_model="proofread-page",
        text="refreshed body",
        revid=99,
        timestamp=NOW,
    )
    wiki = FakeWikiClient(pages={moved: remote}, changes=[_change(moved, minutes=5)])
    client.app.state.client_factory = lambda _site: wiki

    with Session(engine) as session:
        site = _site(session)
        for number in (1, 2, 3):
            _page(session, site, _work_page(number))

    response = client.post(
        "/fetch/refresh", json={"label": LABEL, "since": NOW.isoformat()}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["plan"]["basis"] == "incremental"
    assert body["plan"]["titles"] == [moved]
    assert body["enqueued"] == 1

    # Enqueued, not fetched: the refresh planned the work, the drain does it.
    with Session(engine) as session:
        assert session.exec(select(Page).where(Page.title == moved)).one().text != (
            "refreshed body"
        )

    drain(client)

    with Session(engine) as session:
        page = session.exec(select(Page).where(Page.title == moved)).one()
        assert page.text == "refreshed body"


def test_a_dry_run_plans_without_enqueueing(client, engine) -> None:
    with Session(engine) as session:
        site = _site(session)
        _page(session, site, _work_page(1))

    client.app.state.client_factory = lambda _site: FakeWikiClient(
        changes=[_change(_work_page(1), minutes=5)]
    )

    response = client.post(
        "/fetch/refresh",
        json={"label": LABEL, "since": NOW.isoformat(), "dry_run": True},
    )

    assert response.json()["enqueued"] == 0
    with Session(engine) as session:
        assert session.exec(select(FetchRequest)).all() == []


def test_refresh_rejects_missing_or_null_since_without_queueing(client, engine):
    with Session(engine) as session:
        _site(session)
    for payload in ({"label": LABEL}, {"label": LABEL, "since": None}):
        response = client.post("/fetch/refresh", json=payload)
        assert response.status_code == 422
    with Session(engine) as session:
        assert session.exec(select(FetchRequest)).all() == []


def test_separate_books_and_repeated_calls_do_not_consume_changes(client, engine):
    first = "Page:First.djvu/1"
    second = "Page:Second.djvu/1"
    with Session(engine) as session:
        _site(session)
    client.app.state.client_factory = lambda _site: FakeWikiClient(
        changes=[_change(first, minutes=8), _change(second, minutes=2)]
    )
    for title in (first, second, first):
        response = client.post(
            "/fetch/refresh",
            json={
                "label": LABEL,
                "since": NOW.isoformat(),
                "title_prefix": title.rsplit("/", 1)[0] + "/",
            },
        )
        assert response.status_code == 202
        assert response.json()["plan"]["titles"] == [title]
        assert response.json()["enqueued"] == 1
        assert "watermark" not in response.json()
        assert "watermark" not in response.json()["plan"]
    with Session(engine) as session:
        assert len(session.exec(select(FetchRequest)).all()) == 3
