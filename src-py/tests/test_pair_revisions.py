from datetime import datetime, timedelta, timezone

from conftest import add_proofread_meta
from sqlmodel import Session, select

from wtbot.model import NsRole, Page, RevisionLink, Site
from wtbot.revision_store import record_head_revision, record_history
from wtbot.wiki.wiki_types import RemotePage

"""The revision drill-down: resolving a pair the anchor search will not propose.

`quality_differs` is the shape this exists for. Upstream proofreads a page, so
its head is one level-bump above a revision we hold; we then touch our own copy,
so *our* head has moved too. The anchor search compares each head against the
other side's history one side at a time and, by design, stops there -- a pair
where both sides moved on cannot be resolved by a link it is willing to propose.

But the matching pair is sitting in the two histories, and a person looking at
two columns can see it at a glance. So the drill-down reports every same-content
pair across both histories -- by `comparable_sha1`, the same predicate the
search uses -- and lets a reviewer assert one.
"""

INDEX = "Index:Hertz.pdf"
TITLE = "Page:Hertz.pdf/9"
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def body(level: int, user: str, words: str) -> str:
    return (
        f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>'
        f"{words}<noinclude></noinclude>"
    )


def remote_page(text: str, revid: int, parentid: int | None, days: int) -> RemotePage:
    return RemotePage(
        title=TITLE,
        namespace_key=250,
        namespace_canonical="Page",
        content_model="proofread-page",
        text=text,
        revid=revid,
        parentid=parentid,
        timestamp=WHEN + timedelta(days=days),
    )


def build_site(session: Session, family: str) -> Site:
    site = Site(family=family, code="en", label=family)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def build_page(session: Session, site: Site, revisions: list[RemotePage]) -> Page:
    """A page with a real history: head first, older revisions behind it."""
    page = Page(site_pk=site.pk, title=TITLE, namespace_role=NsRole.page)
    session.add(page)
    session.commit()
    session.refresh(page)
    add_proofread_meta(session, page_pk=page.pk, index_title=INDEX, page_number=9)
    session.commit()

    record_head_revision(session, page, revisions[0])
    record_history(session, page, revisions[1:])
    session.commit()
    return page


def seed_diverged_pair(engine) -> int:
    """The Hertz page 9 shape, with both sides moved on past their agreement.

    local   r12  level 3, "Words."   <- head
            r11  level 2, "Older."      == remote r901
    remote  r902 level 4, "Words."   <- head, a proofread bump
            r901 level 2, "Older."      == local r11

    The heads hold the same words at different levels, so the pair reports
    ``quality_differs``. Neither head matches anything in the other side's
    history either -- each side edited after the point they agreed -- so the
    anchor search has nothing to propose, and the pair that *does* match is one
    revision back on both sides, which is precisely where the search stops.
    """
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")

        local_page = build_page(
            session,
            local,
            [
                remote_page(body(3, "Us", "Words."), 12, 11, 3),
                remote_page(body(2, "Us", "Older."), 11, None, 1),
            ],
        )
        remote_page_row = build_page(
            session,
            remote,
            [
                remote_page(body(4, "Them", "Words."), 902, 901, 4),
                remote_page(body(2, "Them", "Older."), 901, None, 2),
            ],
        )

        from wtbot.page_link_store import pair_pages

        pairing = pair_pages(session, local_page, remote_page_row)
        session.commit()
        return pairing.pk


def test_the_pair_reports_quality_differs_before_any_drill_down(client, engine) -> None:
    """The state the reviewer arrives in: the search has nothing to offer."""
    seed_diverged_pair(engine)
    body_ = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    (proposal,) = client.post("/links/propose", json=body_).json()["proposals"]
    assert proposal["outcome"] == "quality_differs"
    assert proposal["proposable"] is False


def test_the_drill_down_finds_the_match_the_search_would_not_propose(
    client, engine
) -> None:
    """Both sides moved on, so no head matches anything -- but r11 and r901 are
    the same content, and they are right there in the two histories."""
    pair_pk = seed_diverged_pair(engine)

    view = client.get(f"/links/pairs/{pair_pk}/revisions")
    assert view.status_code == 200, view.text
    data = view.json()

    assert [row["revid"] for row in data["local"]] == [12, 11]
    assert [row["revid"] for row in data["remote"]] == [902, 901]
    assert data["local"][0]["is_head"] is True

    (match,) = data["matches"]
    assert (match["local_revid"], match["remote_revid"]) == (11, 901)
    assert match["local_ahead_by"] == 1
    assert match["remote_ahead_by"] == 1
    assert match["is_heads"] is False
    assert match["linked"] is False


def test_the_drill_down_shows_why_the_heads_differ(client, engine) -> None:
    """The level is the whole story on a quality_differs page, and the username
    is why the byte hashes disagree even where the content does not."""
    pair_pk = seed_diverged_pair(engine)
    data = client.get(f"/links/pairs/{pair_pk}/revisions").json()

    local_head, local_older = data["local"]
    remote_head, remote_older = data["remote"]

    assert (local_head["level"], remote_head["level"]) == (3, 4)
    assert (local_older["user"], remote_older["user"]) == ("Us", "Them")
    # Same content, different bytes: the two columns join on comparable_sha1.
    assert local_older["comparable_sha1"] == remote_older["comparable_sha1"]
    assert local_older["content_sha1"] != remote_older["content_sha1"]


def test_a_reviewer_can_assert_the_match_from_the_drill_down(client, engine) -> None:
    """The action the view exists for."""
    pair_pk = seed_diverged_pair(engine)

    created = client.post(
        f"/links/pairs/{pair_pk}/rungs",
        json={"local_revid": 11, "remote_revid": 901, "origin": "manual"},
    )
    assert created.status_code == 201, created.text

    after = client.get(f"/links/pairs/{pair_pk}/revisions").json()
    (match,) = after["matches"]
    assert match["linked"] is True
    assert match["link_pk"] == created.json()["pk"]
    assert len(after["rungs"]) == 1
    # And each side's row names what it is now linked to.
    older = next(row for row in after["local"] if row["revid"] == 11)
    assert older["linked_to"] == [match["remote_revision_pk"]]


def test_the_asserted_rung_belongs_to_the_pairing(client, engine) -> None:
    """Not a stray link: it hangs off the pairing it was asserted within, so
    retracting the ladder takes it."""
    pair_pk = seed_diverged_pair(engine)
    client.post(
        f"/links/pairs/{pair_pk}/rungs", json={"local_revid": 11, "remote_revid": 901}
    )

    with Session(engine) as session:
        (rung,) = session.exec(select(RevisionLink)).all()
        assert rung.page_link_pk == pair_pk

    cleared = client.delete(f"/links/pairs/{pair_pk}/rungs").json()
    assert cleared["rungs_removed"] == 1


def test_asserting_a_pair_that_does_not_match_is_refused(client, engine) -> None:
    """Picking by hand is meant to find the pair that matches, not to bypass
    the question -- a false rung is inherited by everything above it."""
    pair_pk = seed_diverged_pair(engine)

    refused = client.post(
        f"/links/pairs/{pair_pk}/rungs", json={"local_revid": 12, "remote_revid": 902}
    )
    assert refused.status_code == 409
    assert "do not hold the same content" in refused.json()["detail"]

    forced = client.post(
        f"/links/pairs/{pair_pk}/rungs",
        json={"local_revid": 12, "remote_revid": 902, "force": True},
    )
    assert forced.status_code == 201


def test_an_uncached_revision_is_a_404_that_says_what_to_do(client, engine) -> None:
    pair_pk = seed_diverged_pair(engine)
    missing = client.post(
        f"/links/pairs/{pair_pk}/rungs", json={"local_revid": 999, "remote_revid": 901}
    )
    assert missing.status_code == 404
    assert "Fetch more history" in missing.json()["detail"]


def test_matches_are_ordered_by_how_little_would_replay(client, engine) -> None:
    """Several true answers, and the tightest is the one a reviewer wants: an
    older anchor makes a page look more diverged than it is."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        # Two matching pairs: (11, 901) one back on each side, and (10, 900)
        # two back -- a run of touch edits over the same words.
        local_page = build_page(
            session,
            local,
            [
                remote_page(body(3, "Us", "Newer."), 12, 11, 3),
                remote_page(body(3, "Us", "Words."), 11, 10, 2),
                remote_page(body(2, "Us", "Words."), 10, None, 1),
            ],
        )
        remote_page_row = build_page(
            session,
            remote,
            [
                remote_page(body(3, "Them", "Different."), 902, 901, 4),
                remote_page(body(3, "Them", "Words."), 901, 900, 2),
                remote_page(body(2, "Them", "Words."), 900, None, 1),
            ],
        )
        from wtbot.page_link_store import pair_pages

        pair_pk = pair_pages(session, local_page, remote_page_row).pk
        session.commit()

    matches = client.get(f"/links/pairs/{pair_pk}/revisions").json()["matches"]
    assert [(m["local_revid"], m["remote_revid"]) for m in matches] == [
        (11, 901),
        (10, 900),
    ]


def test_incomplete_history_is_reported_rather_than_implied(client, engine) -> None:
    """An absent match means "we did not look far enough" when the history is
    incomplete, and "they never agreed" when it is not. The view says which."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        local_page = build_page(
            session, local, [remote_page(body(3, "Us", "Ours."), 12, None, 1)]
        )
        remote_page_row = build_page(
            session,
            remote,
            # A head whose parent we do not hold: the history stops short.
            [remote_page(body(3, "Them", "Theirs."), 902, 800, 1)],
        )
        from wtbot.page_link_store import pair_pages

        pair_pk = pair_pages(session, local_page, remote_page_row).pk
        session.commit()

    data = client.get(f"/links/pairs/{pair_pk}/revisions").json()
    assert data["matches"] == []
    assert data["local_history_complete"] is True
    assert data["remote_history_complete"] is False


def test_the_drill_down_of_an_unknown_pairing_is_a_404(client) -> None:
    assert client.get("/links/pairs/999/revisions").status_code == 404
