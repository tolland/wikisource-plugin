from datetime import datetime, timezone

from conftest import fake_pageid, make_page
from sqlmodel import Session, select

from wtbot.fetch.revision_store import record_head_revision
from wtbot.model import (
    FetchRequest,
    FetchState,
    PageLink,
    PageTreeLink,
    PromotionBatch,
    RevisionLink,
    Site,
    SiteCredential,
)
from wtbot.title_store import ensure_title
from wtbot.wiki.wiki_types import RemotePage

SOURCE = "The Principles of Psychology (James)"
TARGET = "Book:Psychology"


def add_page(session, site, title, text, revid):
    page = make_page(session, site_pk=site.pk, title=title, content_model="wikitext")
    session.add(page)
    session.flush()
    record_head_revision(
        session,
        page,
        RemotePage(
            title=title,
            namespace_key=0,
            namespace_canonical="",
            content_model="wikitext",
            text=text,
            revid=revid,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            pageid=fake_pageid(title),
        ),
    )
    session.commit()
    return page


def seed(engine):
    with Session(engine) as session:
        source = Site(family="upstream", code="en", label="upstream")
        target = Site(family="local", code="en", label="local")
        session.add_all([source, target])
        session.flush()
        for site in (source, target):
            session.add(SiteCredential(site_pk=site.pk, username="Admin", password="x"))
        add_page(session, source, SOURCE, "Root body", 100)
        add_page(session, target, TARGET, "Root body", 200)
        add_page(session, source, SOURCE + "/Volume 1/Chapter 1", "New chapter", 101)
        missing = ensure_title(
            session,
            site_pk=target.pk,
            title=TARGET + "/Volume 1/Chapter 1",
            expected_content_model="wikitext",
        )
        missing.fetch_status = FetchState.done
        add_page(session, target, TARGET + "/Local appendix", "Only local", 201)
        add_page(session, source, SOURCE + " extended/Outside", "Not a descendant", 102)
        session.commit()


def mapping(client):
    result = client.post(
        "/links/trees",
        json={
            "source_label": "upstream",
            "target_label": "local",
            "source_root": SOURCE.replace(" ", "_"),
            "target_root": TARGET,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()["pk"]


def report(client, pk, reverse=False):
    result = client.post(f"/links/trees/{pk}/report", json={"reverse": reverse})
    assert result.status_code == 200, result.text
    return {row["path"]: row for row in result.json()["rows"]}


def test_maps_nested_paths_across_namespace_and_root_and_reports_both_sides(
    client, engine
):
    seed(engine)
    pk = mapping(client)
    rows = report(client, pk)
    assert set(rows) == {"", "/Volume 1/Chapter 1", "/Local appendix"}
    assert rows[""]["page"]["verdict"] == "unlinked"
    assert rows[""]["proposal"]["proposable"] is True
    chapter = rows["/Volume 1/Chapter 1"]["page"]
    assert chapter["target_title"] == TARGET + "/Volume 1/Chapter 1"
    assert chapter["verdict"] == "create"
    assert rows["/Local appendix"]["page"]["verdict"] == "source_missing"
    assert (
        report(client, pk, reverse=True)["/Volume 1/Chapter 1"]["page"]["actionable"]
        is False
    )
    assert client.get("/links/trees").json()[0]["source_root"] == SOURCE
    assert mapping(client) == pk


def test_pairs_then_confirms_anchors_and_stages_mapped_creates(client, engine):
    seed(engine)
    pk = mapping(client)
    titles = [SOURCE, SOURCE + "/Volume 1/Chapter 1"]
    paired = client.post(f"/links/trees/{pk}/pairs", json={"source_titles": titles})
    assert paired.status_code == 200, paired.text
    with Session(engine) as session:
        assert len(session.exec(select(RevisionLink)).all()) == 0
    confirm = client.post(
        f"/links/trees/{pk}/confirm", json={"source_titles": [SOURCE]}
    )
    assert confirm.status_code == 200, confirm.text
    assert report(client, pk)[""]["page"]["verdict"] == "in_sync"
    staged = client.post(
        f"/links/trees/{pk}/batches", json={"source_titles": titles[1:]}
    )
    assert staged.status_code == 201, staged.text
    batch = staged.json()[0]
    assert batch["target_title"] == TARGET + "/Volume 1/Chapter 1"
    assert batch["promotions"][0]["submitted_body"] == "New chapter"


def test_uncached_mapped_destination_is_unknown_until_fetched(client, engine):
    seed(engine)
    with Session(engine) as session:
        source = session.exec(select(Site).where(Site.label == "upstream")).one()
        add_page(session, source, SOURCE + "/Unfetched", "Unfetched target", 103)
    pk = mapping(client)
    row = report(client, pk)["/Unfetched"]["page"]
    assert row["target_title"] == TARGET + "/Unfetched"
    assert row["verdict"] == "unknown"
    assert row["actionable"] is False
    result = client.post(
        f"/links/trees/{pk}/batches",
        json={"source_titles": [SOURCE + "/Volume 1/Chapter 1", SOURCE + "/Unfetched"]},
    )
    assert result.status_code == 409
    with Session(engine) as session:
        assert session.exec(select(PromotionBatch)).all() == []


def test_fetch_queues_both_roots_and_mapped_counterparts_with_history(client, engine):
    seed(engine)
    pk = mapping(client)
    result = client.post(f"/links/trees/{pk}/fetch", json={"revisions": 20})
    assert result.status_code == 200, result.text
    with Session(engine) as session:
        queued = session.exec(select(FetchRequest)).all()
        assert len(queued) == 6
        assert all(item.revisions == 20 for item in queued)
        assert {item.title for item in queued if item.depth == 1} == {SOURCE, TARGET}
        assert TARGET + "/Volume 1/Chapter 1" in {item.title for item in queued}


def test_outside_selection_rejected_and_unpair_removes_tree_tracking(client, engine):
    from wtbot.linking.page_link_store import unpair

    seed(engine)
    pk = mapping(client)
    result = client.post(
        f"/links/trees/{pk}/pairs",
        json={"source_titles": [SOURCE + " extended/Outside"]},
    )
    assert result.status_code == 422
    with Session(engine) as session:
        unpair(session, session.get(PageLink, pk))
        session.commit()
        assert session.get(PageTreeLink, pk) is None


def test_single_page_create_keeps_an_explicit_uncached_destination(client, engine):
    seed(engine)
    response = client.post(
        "/sync/page-report",
        json={
            "source_label": "upstream",
            "target_label": "local",
            "source_title": SOURCE,
            "target_title": "Book:Another root",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["page"]["target_title"] == "Book:Another root"


def test_confirmed_root_replays_changes_to_the_renamed_root(client, engine):
    from wtbot.model import Page

    seed(engine)
    pk = mapping(client)
    confirmed = client.post(
        f"/links/trees/{pk}/confirm", json={"source_titles": [SOURCE]}
    )
    assert confirmed.status_code == 200, confirmed.text
    with Session(engine) as session:
        source = session.exec(select(Site).where(Site.label == "upstream")).one()
        from wtbot.title_store import page_at

        page = page_at(session, site_pk=source.pk, title=SOURCE)
        assert isinstance(page, Page)
        record_head_revision(
            session,
            page,
            RemotePage(
                title=SOURCE,
                namespace_key=0,
                namespace_canonical="",
                content_model="wikitext",
                text="Revised root",
                revid=104,
                parentid=100,
                timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
                pageid=fake_pageid(SOURCE),
            ),
        )
        session.commit()
    assert report(client, pk)[""]["page"]["verdict"] == "push"
    assert report(client, pk, reverse=True)[""]["page"]["verdict"] == "behind"
    staged = client.post(f"/links/trees/{pk}/batches", json={"source_titles": [SOURCE]})
    assert staged.status_code == 201, staged.text
    assert staged.json()[0]["target_title"] == TARGET
    assert staged.json()[0]["promotions"][0]["submitted_body"] == "Revised root"


def test_saved_tree_mapping_survives_natural_key_restore(client, engine, tmp_path):
    from pathlib import Path

    from wtbot.db import create_db_engine
    from wtbot.maintenance.dump import write_dump
    from wtbot.maintenance.restore import restore_dump
    from wtbot.model import Title

    seed(engine)
    mapping(client)
    archive = tmp_path / "tree.json"
    rebuilt = tmp_path / "rebuilt.db"
    write_dump(Path(engine.url.database), archive)
    restore_dump(archive, rebuilt)
    restored = create_db_engine(f"sqlite:///{rebuilt}")
    try:
        with Session(restored) as session:
            tree = session.exec(select(PageTreeLink)).one()
            pair = session.get(PageLink, tree.pk)
            assert session.get(Title, pair.local_page_pk).title == SOURCE
            assert session.get(Title, pair.remote_page_pk).title == TARGET
    finally:
        restored.dispose()
