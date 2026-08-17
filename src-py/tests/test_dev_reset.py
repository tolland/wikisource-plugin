import httpx
import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app
from wtbot.dev_reset import (
    execute_fetchrequest_reset,
    execute_promotion_reset,
    execute_promotionbatch_reset,
    plan_fetchrequest_reset,
    plan_promotion_reset,
    plan_promotionbatch_reset,
)
from wtbot.model import (
    FetchRequest,
    Page,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    Revision,
    Site,
)


def _seed_reset_rows(engine) -> None:
    with Session(engine) as session:
        source_site = Site(family="source", code="en", label="source")
        target_site = Site(family="target", code="en", label="target")
        session.add_all([source_site, target_site])
        session.flush()

        source_page = Page(site_pk=source_site.pk, title="Page:Book/1")
        target_page = Page(site_pk=target_site.pk, title="Page:Book/1")
        session.add_all([source_page, target_page])
        session.flush()
        revision = Revision(page_pk=source_page.pk, revid=10)
        session.add(revision)
        session.flush()

        batch = PromotionBatch(
            source_site_pk=source_site.pk,
            target_site_pk=target_site.pk,
            source_page_pk=source_page.pk,
            target_page_pk=target_page.pk,
            source_title=source_page.title,
            target_title=target_page.title,
        )
        session.add(batch)
        session.flush()
        session.add(
            Promotion(
                batch_pk=batch.pk,
                intent=PromotionIntent.update,
                source_revision_pk=revision.pk,
                base_revid=9,
                body="new body",
            )
        )

        parent = FetchRequest(site_pk=source_site.pk, title="Index:Book")
        session.add(parent)
        session.flush()
        session.add(
            FetchRequest(
                site_pk=source_site.pk,
                parent_pk=parent.pk,
                title=source_page.title,
            )
        )
        session.commit()


def test_promotion_reset_only_empties_promotion(engine):
    _seed_reset_rows(engine)

    with Session(engine) as session:
        preview = plan_promotion_reset(session)
        assert preview.model_dump() == {"counts": [{"table": "promotion", "rows": 1}]}
        assert execute_promotion_reset(session) == preview

    with Session(engine) as session:
        assert session.exec(select(Promotion)).all() == []
        assert len(session.exec(select(PromotionBatch)).all()) == 1
        assert len(session.exec(select(FetchRequest)).all()) == 2


def test_promotionbatch_reset_also_empties_promotion(engine):
    _seed_reset_rows(engine)

    with Session(engine) as session:
        preview = plan_promotionbatch_reset(session)
        assert preview.model_dump() == {
            "counts": [
                {"table": "promotion", "rows": 1},
                {"table": "promotionbatch", "rows": 1},
            ]
        }
        assert execute_promotionbatch_reset(session) == preview

    with Session(engine) as session:
        assert session.exec(select(Promotion)).all() == []
        assert session.exec(select(PromotionBatch)).all() == []
        assert len(session.exec(select(FetchRequest)).all()) == 2


def test_fetchrequest_reset_only_empties_fetchrequest(engine):
    _seed_reset_rows(engine)

    with Session(engine) as session:
        preview = plan_fetchrequest_reset(session)
        assert preview.model_dump() == {
            "counts": [{"table": "fetchrequest", "rows": 2}]
        }
        assert execute_fetchrequest_reset(session) == preview

    with Session(engine) as session:
        assert session.exec(select(FetchRequest)).all() == []
        assert len(session.exec(select(Promotion)).all()) == 1
        assert len(session.exec(select(PromotionBatch)).all()) == 1
        assert len(session.exec(select(Site)).all()) == 2
        assert len(session.exec(select(Page)).all()) == 2
        assert len(session.exec(select(Revision)).all()) == 1


@pytest.fixture
def cli_api(monkeypatch):
    calls = {"get": [], "delete": []}
    plan = {
        "counts": [
            {"table": "promotion", "rows": 4},
            {"table": "promotionbatch", "rows": 2},
            {"table": "fetchrequest", "rows": 7},
        ]
    }

    def fake_get(url, params=None, timeout=None):
        calls["get"].append(url)
        return httpx.Response(200, json=plan, request=httpx.Request("GET", url))

    def fake_delete(url, timeout=None):
        calls["delete"].append(url)
        return httpx.Response(200, json=plan, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "delete", fake_delete)
    return calls


@pytest.mark.parametrize(
    ("command", "endpoint"),
    [
        ("reset-promotion", "/dev/promotion/reset-plan"),
        ("reset-promotionbatch", "/dev/promotionbatch/reset-plan"),
        ("reset-fetchrequest", "/dev/fetchrequest/reset-plan"),
    ],
)
def test_dev_reset_commands_are_dry_runs_without_force(cli_api, command, endpoint):
    result = CliRunner().invoke(create_app(), ["dev", command])

    assert result.exit_code == 0, result.output
    assert cli_api["get"][0].endswith(endpoint)
    assert cli_api["delete"] == []
    assert "would delete" in result.output
    assert "nothing deleted" in result.output


@pytest.mark.parametrize(
    ("command", "endpoint"),
    [
        ("reset-promotion", "/dev/promotion"),
        ("reset-promotionbatch", "/dev/promotionbatch"),
        ("reset-fetchrequest", "/dev/fetchrequest"),
    ],
)
def test_dev_reset_commands_execute_with_force(cli_api, command, endpoint):
    result = CliRunner().invoke(create_app(), ["dev", command, "--force"])

    assert result.exit_code == 0, result.output
    assert cli_api["get"] == []
    assert cli_api["delete"][0].endswith(endpoint)
    assert "deleted" in result.output
