from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.index_link_store import link_indexes, work_for_index_page
from wtbot.model import (
    FetchRequest,
    IndexLink,
    NsRole,
    Page,
    PageLink,
    PageMeta,
    RevisionLink,
    Site,
    SiteCredential,
)
from wtbot.revision_store import record_head_revision
from wtbot.wiki.wiki_types import RemotePage

"""Works: the cross-site unit a reviewer navigates, and the two-level drill.

The page surface answers questions about a pair you can already name. A
reviewer arrives knowing only "we track this book against upstream", so the
entry point has to be the work -- and the work has to know its pages without
matching titles back through `PageMeta.index_title`.

The cases these tests are built around are the two the page listing reports and
could not act on:

    history_exhausted  no anchor in the revisions held, and we do not hold all
    quality_differs    same words, different level, no anchor either

Neither is a verdict. Both are usually one fetch away from an anchor, and the
workflow's job is to make that fetch reachable from the row that reported it.
"""

INDEX = "Index:Canadian patent 29537.djvu"
REMOTE_INDEX = "Index:Canadian patent 29537 (upstream).djvu"


def body(level: int, user: str, words: str) -> str:
    return (
        f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>'
        f"{words}<noinclude></noinclude>"
    )


def build_site(session: Session, family: str) -> Site:
    site = Site(family=family, code="en", label=family)
    session.add(site)
    session.commit()
    session.refresh(site)
    # Both sides must be able to log in before a fetch can be queued.
    session.add(SiteCredential(site_pk=site.pk, username="Admin", password="secret"))
    session.commit()
    return site


def build_index(session: Session, site: Site, title: str) -> Page:
    page = Page(
        site_pk=site.pk,
        title=title,
        namespace_role=NsRole.index,
        content_model="proofread-index",
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


def build_page(
    session: Session,
    site: Site,
    index_title: str,
    number: int,
    *,
    text: str,
    revid: int,
    parentid: int | None = None,
    title: str | None = None,
) -> Page:
    """One Page: of a work.

    ``parentid`` is the lever these tests turn: a head whose parent we do not
    hold makes the stored history incomplete, which is what separates
    "we did not look far enough" from "they disagree".
    """
    title = title or f"Page:Canadian patent 29537.djvu/{number}"
    page = Page(site_pk=site.pk, title=title, namespace_role=NsRole.page)
    session.add(page)
    session.commit()
    session.refresh(page)
    session.add(PageMeta(page_pk=page.pk, index_title=index_title, page_number=number))
    session.commit()
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
            parentid=parentid,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    session.commit()
    return page


def seed_work(engine) -> None:
    """A three-page work whose pages cover the two unresolved outcomes.

    1. same words, same level                 -> linkable
    2. same words, different level, no anchor -> quality_differs
    3. different words, incomplete history    -> history_exhausted
    """
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        build_index(session, local, INDEX)
        build_index(session, remote, REMOTE_INDEX)

        build_page(session, local, INDEX, 1, text=body(3, "Us", "Same."), revid=5)
        build_page(
            session, remote, REMOTE_INDEX, 1, text=body(3, "Them", "Same."), revid=900
        )

        build_page(session, local, INDEX, 2, text=body(3, "Us", "Words."), revid=6)
        build_page(
            session, remote, REMOTE_INDEX, 2, text=body(4, "Them", "Words."), revid=901
        )

        build_page(
            session,
            local,
            INDEX,
            3,
            text=body(3, "Us", "Ours."),
            revid=7,
            parentid=4,
        )
        build_page(
            session,
            remote,
            REMOTE_INDEX,
            3,
            text=body(3, "Them", "Theirs."),
            revid=902,
            parentid=800,
        )


LINK_BODY = {
    "local_label": "mywikisource",
    "remote_label": "wikisource",
    "index_title": INDEX,
    "remote_index_title": REMOTE_INDEX,
}


# -- the store ---------------------------------------------------------------


def test_a_work_is_a_pairing_of_two_index_pages(session: Session) -> None:
    """The whole reason IndexLink is a side table: the work-level claim is a
    page pairing, so it gets the pairing machinery -- and a ladder over the
    index bodies -- rather than a parallel one."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_index = build_index(session, local, INDEX)
    remote_index = build_index(session, remote, REMOTE_INDEX)

    work = link_indexes(session, local_index, remote_index)
    session.commit()

    pairing = session.get(PageLink, work.page_link_pk)
    assert {pairing.local_page_pk, pairing.remote_page_pk} == {
        local_index.pk,
        remote_index.pk,
    }


def test_linking_a_work_twice_returns_the_same_work(session: Session) -> None:
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_index = build_index(session, local, INDEX)
    remote_index = build_index(session, remote, REMOTE_INDEX)

    first = link_indexes(session, local_index, remote_index)
    # Reversed, because the pair is unordered and a second identity for one
    # work would double every count the viewer renders.
    second = link_indexes(session, remote_index, local_index)
    session.commit()

    assert first.pk == second.pk
    assert len(session.exec(select(IndexLink)).all()) == 1


def test_a_work_adopts_page_pairs_made_before_it(session: Session) -> None:
    """Pairing a work's pages and declaring the work tracked happen in either
    order, so linking claims what is already there."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_index = build_index(session, local, INDEX)
    remote_index = build_index(session, remote, REMOTE_INDEX)
    local_page = build_page(session, local, INDEX, 1, text="a", revid=5)
    remote_page = build_page(session, remote, REMOTE_INDEX, 1, text="a", revid=900)

    from wtbot.page_link_store import pair_pages

    pairing = pair_pages(session, local_page, remote_page)
    session.commit()
    assert pairing.index_link_pk is None

    work = link_indexes(session, local_index, remote_index)
    session.commit()
    session.refresh(pairing)
    assert pairing.index_link_pk == work.pk


def test_only_index_pages_can_be_a_work(session: Session) -> None:
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, INDEX, 1, text="a", revid=5)
    remote_index = build_index(session, remote, REMOTE_INDEX)

    from wtbot.remote_link_store import LinkError

    try:
        link_indexes(session, local_page, remote_index)
    except LinkError as exc:
        assert "not an Index: page" in str(exc)
    else:  # pragma: no cover - the assertion is the test
        raise AssertionError("a Page: was accepted as a work")


# -- level 1 -----------------------------------------------------------------


def test_tracking_a_work_pairs_its_pages(client, engine) -> None:
    seed_work(engine)

    created = client.post("/links/works", json=LINK_BODY)
    assert created.status_code == 201, created.text
    result = created.json()

    assert result["created"] is True
    assert result["paired"] == 3
    assert result["unpaired"] == []
    assert result["work"]["pairs"] == 3
    assert result["work"]["local_title"] == INDEX
    assert result["work"]["remote_title"] == REMOTE_INDEX


def test_the_work_list_is_the_viewer_entry_point(client, engine) -> None:
    """One call, both sides named, cheap counts -- no walking back from
    pagelink rows through index titles."""
    seed_work(engine)
    client.post("/links/works", json=LINK_BODY)

    works = client.get("/links/works").json()["works"]
    assert len(works) == 1
    (work,) = works
    assert work["local_site"] == "mywikisource"
    assert work["remote_site"] == "wikisource"
    assert work["pairs"] == 3
    assert work["local_pages"] == 3
    assert work["linked"] == 0


def test_the_work_list_can_be_narrowed_to_a_site_pair(client, engine) -> None:
    seed_work(engine)
    client.post("/links/works", json=LINK_BODY)

    matching = client.get(
        "/links/works",
        params={"local_label": "mywikisource", "remote_label": "wikisource"},
    )
    assert len(matching.json()["works"]) == 1

    # Asked the other way round, it is the same work: which side was called
    # local records how the assertion was made, not a hierarchy.
    reversed_ = client.get(
        "/links/works",
        params={"local_label": "wikisource", "remote_label": "mywikisource"},
    )
    assert len(reversed_.json()["works"]) == 1


def test_candidates_show_which_indexes_are_already_tracked(client, engine) -> None:
    """One column of the two-column picker: every cached index on a site, with
    its work if it has one, so the column can sort tracked first."""
    seed_work(engine)
    client.post("/links/works", json=LINK_BODY)

    listed = client.get("/links/works/candidates", params={"label": "mywikisource"})
    assert listed.status_code == 200, listed.text
    body_ = listed.json()
    assert body_["site"] == "mywikisource"
    (candidate,) = body_["indexes"]
    assert candidate["title"] == INDEX
    assert candidate["work_pk"] is not None
    assert candidate["paired_with"] == REMOTE_INDEX
    assert candidate["cached_pages"] == 3


def test_candidates_need_a_site(client) -> None:
    assert client.get("/links/works/candidates").status_code == 400


# -- level 2 -----------------------------------------------------------------


def test_the_work_detail_names_the_two_unresolved_cases(client, engine) -> None:
    """The list a reviewer works down, and the reason this endpoint exists:
    page 2 is quality_differs, page 3 is history_exhausted, and both are
    flagged as things a fetch could move."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    detail = client.get(f"/links/works/{work_pk}").json()

    outcomes = {row["page_number"]: row["outcome"] for row in detail["pages"]}
    assert outcomes == {
        1: "same",
        2: "quality_differs",
        3: "history_exhausted",
    }
    assert detail["counts"]["quality_differs"] == 1
    assert detail["needs_history"] == 2

    by_number = {row["page_number"]: row for row in detail["pages"]}
    assert by_number[2]["significance"] == "metadata_significant"
    assert by_number[2]["resolvable_by_fetch"] is True
    assert by_number[3]["resolvable_by_fetch"] is True
    assert by_number[1]["resolvable_by_fetch"] is False
    # Every row carries its pairing, so a row is actionable without a lookup.
    assert all(row["pair_pk"] for row in detail["pages"])


def test_the_work_detail_is_ordered_for_reading(client, engine) -> None:
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    pages = client.get(f"/links/works/{work_pk}").json()["pages"]
    assert [row["page_number"] for row in pages] == [1, 2, 3]


def test_proposing_from_a_work_links_what_it_can(client, engine) -> None:
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    reported = client.post(f"/links/works/{work_pk}/propose", json={}).json()
    assert reported["confirmed"] == 0
    assert reported["counts"]["same"] == 1

    written = client.post(
        f"/links/works/{work_pk}/propose", json={"confirm": True}
    ).json()
    assert written["confirmed"] == 1

    # The rung belongs to the work, so the list view's count moves.
    (work,) = client.get("/links/works").json()["works"]
    assert work["linked"] == 1


# -- resolution --------------------------------------------------------------


def test_fetch_history_queues_both_sides_of_the_stuck_pages(client, engine) -> None:
    """The action the two unresolved outcomes call for. Both sides are queued
    because either can hold the revision that matches."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    result = client.post(
        f"/links/works/{work_pk}/fetch-history", json={"revisions": 12}
    )
    assert result.status_code == 200, result.text
    assert result.json()["pages"] == 2
    assert result.json()["queued"] == 4

    with Session(engine) as session:
        requests = session.exec(select(FetchRequest)).all()
    assert {r.revisions for r in requests} == {12}
    assert {r.kind.value for r in requests} == {"page"}
    # Page 1 is already linkable; queueing it would be requests spent on a
    # question that is answered.
    assert not any(r.title.endswith("/1") for r in requests)
    assert len({r.site_pk for r in requests}) == 2


def test_fetch_history_can_be_asked_for_the_whole_work(client, engine) -> None:
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    result = client.post(
        f"/links/works/{work_pk}/fetch-history", json={"all_pages": True}
    ).json()
    assert result["pages"] == 3
    assert result["queued"] == 6


def test_fetch_history_refuses_a_site_that_cannot_log_in(client, engine) -> None:
    """Checked at queue time, not drain time: a credential failure minutes
    later lands on a row nobody is watching."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]
    with Session(engine) as session:
        credential = session.exec(select(SiteCredential)).first()
        session.delete(credential)
        session.commit()

    refused = client.post(f"/links/works/{work_pk}/fetch-history", json={})
    assert refused.status_code == 409
    with Session(engine) as session:
        assert session.exec(select(FetchRequest)).all() == []


# -- untracking --------------------------------------------------------------


def test_untracking_a_work_releases_its_pairs(client, engine) -> None:
    """ "We no longer track this against that" says nothing about whether the
    pages correspond, and the pairs carry ladders that cost real fetches."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]
    client.post(f"/links/works/{work_pk}/propose", json={"confirm": True})

    removed = client.delete(f"/links/works/{work_pk}").json()
    assert removed == {"deleted": work_pk, "cascade": False, "pairs_released": 3}

    assert client.get("/links/works").json()["works"] == []
    with Session(engine) as session:
        pairs = session.exec(select(PageLink)).all()
        assert len(pairs) == 3  # the index pairing went; the page pairs stayed
        assert all(pair.index_link_pk is None for pair in pairs)
        assert len(session.exec(select(RevisionLink)).all()) == 1


def test_untracking_with_cascade_discards_the_pairs(client, engine) -> None:
    """For the case the untracking is meant to fix: a work linked to the wrong
    work, where every pair under it was asserted about the wrong pages."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]
    client.post(f"/links/works/{work_pk}/propose", json={"confirm": True})

    removed = client.delete(f"/links/works/{work_pk}", params={"cascade": True}).json()
    assert removed["pairs_deleted"] == 3

    with Session(engine) as session:
        assert session.exec(select(PageLink)).all() == []
        assert session.exec(select(RevisionLink)).all() == []


def test_untracking_an_unknown_work_is_a_404(client) -> None:
    assert client.delete("/links/works/999").status_code == 404


def test_the_works_route_is_not_shadowed_by_the_link_pk_route(client) -> None:
    """`/links/works` is registered before `DELETE /links/{link_pk}`; without
    that ordering the request 422s on parsing "works" as an int rather than
    404ing, which is the kind of failure that reads as a client bug."""
    assert client.get("/links/works").status_code == 200
    assert client.delete("/links/works/999").status_code == 404


def test_a_page_pair_knows_its_work(session: Session) -> None:
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_index = build_index(session, local, INDEX)
    remote_index = build_index(session, remote, REMOTE_INDEX)
    work = link_indexes(session, local_index, remote_index)
    session.commit()

    assert work_for_index_page(session, local_index.pk).pk == work.pk
    assert work_for_index_page(session, remote_index.pk).pk == work.pk


# -- link state, separate from what a comparison proposes ---------------------


def test_a_pair_reports_its_link_state_beside_the_proposal(client, engine) -> None:
    """Two different questions, and the column that answered both was
    confusing: `remote_ahead` describes what confirming *would* assert, and
    says nothing about whether anybody has. A pair reading "remote ahead" with
    no rung behind it looks like a state it is not in."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]

    before = client.get(f"/links/works/{work_pk}").json()
    row = next(p for p in before["pages"] if p["page_number"] == 1)
    assert row["outcome"] == "same"  # what confirming would assert
    assert row["linked"] is False  # ...and nobody has
    assert row["needs_attention"] is True
    assert before["needs_attention"] == 3
    assert before["settled"] == 0

    client.post(f"/links/works/{work_pk}/propose", json={"confirm": True})

    after = client.get(f"/links/works/{work_pk}").json()
    row = next(p for p in after["pages"] if p["page_number"] == 1)
    assert row["linked"] is True
    assert row["anchor_is_current"] is True
    # Linked and current: nothing left to do, so this page's list should stop
    # showing it.
    assert row["needs_attention"] is False
    assert after["settled"] == 1
    assert after["needs_attention"] == 2


def test_a_linked_pair_that_has_moved_still_needs_attention(client, engine) -> None:
    """Linked is not the same as done. A pair whose anchor has fallen behind
    its heads is exactly what a reviewer came to find."""
    seed_work(engine)
    work_pk = client.post("/links/works", json=LINK_BODY).json()["work"]["pk"]
    client.post(f"/links/works/{work_pk}/propose", json={"confirm": True})

    with Session(engine) as session:
        local = session.exec(select(Site).where(Site.label == "mywikisource")).one()
        page = session.exec(
            select(Page).where(
                Page.site_pk == local.pk,
                Page.title == "Page:Canadian patent 29537.djvu/1",
            )
        ).one()
        record_head_revision(
            session,
            page,
            RemotePage(
                title=page.title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=body(3, "Us", "Same, but edited."),
                revid=99,
                parentid=5,
                timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        )
        session.commit()

    data = client.get(f"/links/works/{work_pk}").json()
    row = next(p for p in data["pages"] if p["page_number"] == 1)
    assert row["linked"] is True
    assert row["anchor_is_current"] is False
    assert row["needs_attention"] is True
