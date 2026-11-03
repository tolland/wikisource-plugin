import httpx
import pytest
from sqlmodel import Session, select
from test_page_trees import SOURCE, TARGET, mapping, seed
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app
from wtbot.model import (
    PageLink,
    PageTreeLink,
    PromotionBatch,
    Revision,
    RevisionLink,
    Site,
)
from wtbot.title_store import page_at


def test_cache_delete_removes_root_links_and_revisions_but_keeps_counterpart(
    client, engine
):
    seed(engine)
    pk = mapping(client)
    assert (
        client.post(
            f"/links/trees/{pk}/confirm", json={"source_titles": [SOURCE]}
        ).status_code
        == 200
    )
    params = {"label": "upstream", "title": SOURCE.replace(" ", "_")}
    preview = client.delete("/cache/title", params=params)
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    with Session(engine) as session:
        assert session.get(PageTreeLink, pk) is not None
        assert session.exec(select(RevisionLink)).first() is not None
    deleted = client.delete("/cache/title", params=params | {"dry_run": False})
    assert deleted.status_code == 200, deleted.text
    with Session(engine) as session:
        assert session.get(PageTreeLink, pk) is None
        assert session.get(PageLink, pk) is None
        assert session.exec(select(RevisionLink)).all() == []
        target = session.exec(select(Site).where(Site.label == "local")).one()
        assert page_at(session, site_pk=target.pk, title=TARGET) is not None
        source = session.exec(select(Site).where(Site.label == "upstream")).one()
        assert page_at(session, site_pk=source.pk, title=SOURCE) is None
        assert (
            page_at(session, site_pk=source.pk, title=SOURCE + "/Volume 1/Chapter 1")
            is not None
        )
        assert session.exec(select(Revision).where(Revision.revid == 100)).all() == []


def test_cache_delete_removes_related_batch(client, engine):
    seed(engine)
    pk = mapping(client)
    title = SOURCE + "/Volume 1/Chapter 1"
    staged = client.post(f"/links/trees/{pk}/batches", json={"source_titles": [title]})
    assert staged.status_code == 201, staged.text
    result = client.delete(
        "/cache/title", params={"label": "upstream", "title": title, "dry_run": False}
    )
    assert result.status_code == 200, result.text
    with Session(engine) as session:
        assert session.exec(select(PromotionBatch)).all() == []


def test_cache_delete_protects_dirty_title(client, engine):
    seed(engine)
    with Session(engine) as session:
        source = session.exec(select(Site).where(Site.label == "upstream")).one()
        page = page_at(session, site_pk=source.pk, title=SOURCE)
        page.address.dirty = True
        session.add(page.address)
        session.commit()
    params = {"label": "upstream", "title": SOURCE, "dry_run": False}
    assert client.delete("/cache/title", params=params).status_code == 409
    assert (
        client.delete(
            "/cache/title", params=params | {"discard_local_edits": True}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("force", [False, True])
def test_page_delete_cli_uses_backend_and_previews_by_default(monkeypatch, force):
    calls = []

    def fake_delete(url, params=None, timeout=None):
        calls.append((url, params))
        return httpx.Response(
            200,
            json={
                "title": SOURCE,
                "site_label": "Wikisource",
                "dry_run": params["dry_run"],
                "counts": [{"table": "revision", "rows": 120}],
            },
            request=httpx.Request("DELETE", url),
        )

    monkeypatch.setattr(httpx, "delete", fake_delete)
    command = ["page", "delete", "--label", "Wikisource", SOURCE]
    if force:
        command.append("--force")
    result = CliRunner().invoke(create_app(), command)
    assert result.exit_code == 0, result.output
    assert calls[0][0].endswith("/cache/title")
    assert calls[0][1]["dry_run"] is not force
    assert "revision: 120" in result.output
