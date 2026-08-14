from datetime import datetime, timezone

import pytest
from conftest import add_proofread_meta
from sqlmodel import Session, select

from wtbot.matching import compare_pages, confirm_proposals
from wtbot.model import (
    LinkOrigin,
    NsRole,
    Page,
    PageLink,
    RevisionLink,
    Site,
)
from wtbot.page_link_store import find_pair, pair_pages, unpair
from wtbot.remote_link_store import LinkError
from wtbot.revision_store import record_head_revision
from wtbot.wiki.wiki_types import RemotePage

"""Page pairings: the mutable half of correspondence.

The split is the point. "These two pages are the same page" is a claim about
the present -- it can be wrong, and it is corrected by deletion. "These two
revisions hold the same content" is a claim about two immutable objects -- it
cannot stop being true, so it is superseded, never edited.

The pairing also has to exist for pages with *nothing* linkable: a diverged
pair, or one whose other side has not been fetched. Those are exactly the pages
a reviewer needs to see, and the old derived-from-revisions correspondence made
them vanish.
"""

INDEX = "Index:Canadian patent 29537.djvu"


def build_site(session: Session, family: str) -> Site:
    site = Site(family=family, code="en", label=family)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def build_page(
    session: Session, site: Site, number: int, *, body: str | None, revid: int
) -> Page:
    title = f"Page:Canadian patent 29537.djvu/{number}"
    page = Page(site_pk=site.pk, title=title, namespace_role=NsRole.page)
    session.add(page)
    session.commit()
    session.refresh(page)
    add_proofread_meta(session, page_pk=page.pk, index_title=INDEX, page_number=number)
    session.commit()
    if body is not None:
        record_head_revision(
            session,
            page,
            RemotePage(
                title=title,
                namespace_key=104,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=body,
                revid=revid,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        session.commit()
    return page


def test_a_diverged_pair_can_still_be_paired(session: Session) -> None:
    """The case derivation could not represent. Two pages that disagree are
    still two copies of one page, and a reviewer needs to see them listed."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Ours.", revid=5)
    remote_page = build_page(session, remote, 1, body="Theirs.", revid=900)

    link = pair_pages(session, local_page, remote_page)
    session.commit()

    assert link.pk is not None
    # Paired, with nothing linked under it -- which is the honest state.
    assert session.exec(select(RevisionLink)).all() == []


def test_an_unfetched_side_can_still_be_paired(session: Session) -> None:
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Ours.", revid=5)
    remote_page = build_page(session, remote, 1, body=None, revid=0)

    assert pair_pages(session, local_page, remote_page).pk is not None


def test_pairing_is_idempotent_and_keeps_its_orientation(session: Session) -> None:
    """Flipping the orientation would silently reverse the ladder every rung
    under it is written in."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Same.", revid=5)
    remote_page = build_page(session, remote, 1, body="Same.", revid=900)

    first = pair_pages(session, local_page, remote_page, origin=LinkOrigin.copy)
    session.commit()
    again = pair_pages(session, remote_page, local_page, origin=LinkOrigin.manual)
    session.commit()

    assert again.pk == first.pk
    assert again.origin is LinkOrigin.copy
    assert again.local_page_pk == local_page.pk
    assert len(session.exec(select(PageLink)).all()) == 1


def test_two_pages_of_one_site_cannot_be_paired(session: Session) -> None:
    local = build_site(session, "mywikisource")
    first = build_page(session, local, 1, body="A.", revid=1)
    second = build_page(session, local, 2, body="B.", revid=2)

    with pytest.raises(LinkError, match="across sites"):
        pair_pages(session, first, second)


def test_a_revision_link_materialises_its_pairing(session: Session) -> None:
    """Asserting two revisions correspond asserts their pages do, so the
    pairing is created rather than left for a caller to remember."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Same.", revid=5)
    remote_page = build_page(session, remote, 1, body="Same.", revid=900)

    proposal = compare_pages(session, local_page, remote_page)
    (link,) = confirm_proposals(session, [proposal])
    session.commit()

    pairing = find_pair(session, local_page.pk, remote_page.pk)
    assert pairing is not None
    assert link.page_link_pk == pairing.pk


def test_unpairing_takes_its_rungs_with_it(session: Session) -> None:
    """A rung asserted within a pairing nobody now claims is not a fact worth
    keeping -- and leaving it would let a later pairing inherit assertions made
    under a different one."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Same.", revid=5)
    remote_page = build_page(session, remote, 1, body="Same.", revid=900)
    confirm_proposals(session, [compare_pages(session, local_page, remote_page)])
    session.commit()

    pairing = find_pair(session, local_page.pk, remote_page.pk)
    removed = unpair(session, pairing)
    session.commit()

    assert removed == 1
    assert session.exec(select(PageLink)).all() == []
    assert session.exec(select(RevisionLink)).all() == []


def test_a_pairing_survives_a_rename(session: Session) -> None:
    """Pairings name page pks, never titles: a page moved on either wiki keeps
    its pairing, which is the whole reason this is stored rather than
    recomputed from titles."""
    local, remote = build_site(session, "mywikisource"), build_site(
        session, "wikisource"
    )
    local_page = build_page(session, local, 1, body="Same.", revid=5)
    remote_page = build_page(session, remote, 1, body="Same.", revid=900)
    pairing = pair_pages(session, local_page, remote_page)
    session.commit()

    remote_page.title = "Page:Renamed upstream.djvu/1"
    session.add(remote_page)
    session.commit()

    assert find_pair(session, local_page.pk, remote_page.pk).pk == pairing.pk


def test_the_api_lists_pairs_for_a_work_in_reading_order(client, engine) -> None:
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        for number in (3, 1, 2):
            build_page(session, local, number, body="Same.", revid=number)
            build_page(session, remote, number, body="Same.", revid=900 + number)

    created = client.post(
        "/links/pairs/index",
        json={
            "local_label": "mywikisource",
            "remote_label": "wikisource",
            "index_title": INDEX,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json() == {"paired": 3, "created": 3, "unpaired": []}

    listed = client.get("/links/pairs").json()["pairs"]
    assert [row["page_number"] for row in listed] == [1, 2, 3]
    # Paired, nothing asserted about content yet.
    assert all(row["rungs"] == 0 for row in listed)


def test_pairing_a_work_that_does_not_line_up_is_refused(client, engine) -> None:
    """A work missing counterparts is nearly always a wrong --to or a different
    scan; pairing the pages that happen to match would bury that."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        for number in (1, 2, 3):
            build_page(session, local, number, body="Same.", revid=number)
        build_page(session, remote, 1, body="Same.", revid=901)

    body = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    refused = client.post("/links/pairs/index", json=body)
    assert refused.status_code == 409
    assert "have no counterpart" in refused.json()["detail"]

    forced = client.post("/links/pairs/index", json={**body, "strict": False})
    assert forced.status_code == 201
    assert forced.json()["paired"] == 1
    assert len(forced.json()["unpaired"]) == 2


def test_deleting_a_pairing_removes_its_rungs(client, engine) -> None:
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        build_page(session, local, 1, body="Same.", revid=5)
        build_page(session, remote, 1, body="Same.", revid=900)

    body = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    client.post("/links/pairs/index", json=body)
    client.post("/links/propose", json={**body, "confirm": True})

    (row,) = client.get("/links/pairs").json()["pairs"]
    assert row["rungs"] == 1

    removed = client.delete(f"/links/pairs/{row['pk']}")
    assert removed.json() == {"deleted": row["pk"], "rungs_removed": 1}
    assert client.get("/links/pairs").json()["pairs"] == []


def test_a_single_rung_can_be_removed_as_a_mistake(client, engine) -> None:
    """The one exception to append-only, and it is for mistakes rather than
    history: a rung asserted in error was never true."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        build_page(session, local, 1, body="Same.", revid=5)
        build_page(session, remote, 1, body="Same.", revid=900)

    body = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    client.post("/links/propose", json={**body, "confirm": True})
    with Session(engine) as session:
        (link,) = session.exec(select(RevisionLink)).all()

    removed = client.delete(f"/links/{link.pk}").json()
    assert removed == {"deleted": link.pk, "pairing": link.page_link_pk}
    # The pairing outlives the rung: the pages are still the same page.
    assert len(client.get("/links/pairs").json()["pairs"]) == 1


def test_a_ladder_can_be_cleared_without_losing_the_pairing(client, engine) -> None:
    """The retraction `unpair` is too wide for. Links proposed against the
    wrong other side are wrong about the revisions; that the two pages are the
    same page is not in doubt, and re-pairing to re-propose is busywork."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        build_page(session, local, 1, body="Same.", revid=5)
        build_page(session, remote, 1, body="Same.", revid=900)

    body = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    client.post("/links/propose", json={**body, "confirm": True})
    (row,) = client.get("/links/pairs").json()["pairs"]
    assert row["rungs"] == 1

    cleared = client.delete(f"/links/pairs/{row['pk']}/rungs")
    assert cleared.json() == {"pairing": row["pk"], "rungs_removed": 1}

    (still_paired,) = client.get("/links/pairs").json()["pairs"]
    assert still_paired["pk"] == row["pk"]
    assert still_paired["rungs"] == 0
    assert still_paired["page_number"] == 1

    # And the pair is proposable again without being paired again.
    again = client.post("/links/propose", json={**body, "confirm": True})
    assert again.json()["confirmed"] == 1


def test_clearing_a_ladder_leaves_other_pairings_alone(client, engine) -> None:
    """`retract_rungs` is keyed on the pairing, not on the work: clearing one
    page's ladder must not touch its neighbour's."""
    with Session(engine) as session:
        local = build_site(session, "mywikisource")
        remote = build_site(session, "wikisource")
        for number in (1, 2):
            build_page(session, local, number, body=f"Page {number}.", revid=5 + number)
            build_page(
                session, remote, number, body=f"Page {number}.", revid=900 + number
            )

    body = {
        "local_label": "mywikisource",
        "remote_label": "wikisource",
        "index_title": INDEX,
    }
    client.post("/links/propose", json={**body, "confirm": True})
    first, second = client.get("/links/pairs").json()["pairs"]

    client.delete(f"/links/pairs/{first['pk']}/rungs")

    by_pk = {row["pk"]: row for row in client.get("/links/pairs").json()["pairs"]}
    assert by_pk[first["pk"]]["rungs"] == 0
    assert by_pk[second["pk"]]["rungs"] == 1


def test_clearing_the_ladder_of_an_unknown_pairing_is_a_404(client) -> None:
    assert client.delete("/links/pairs/9999/rungs").status_code == 404
