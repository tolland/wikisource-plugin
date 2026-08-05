import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

"""The fetch-refresh CLI, and the contract its output rests on.

The command is a thin client over ``POST /fetch/refresh``, so what is worth
testing is the part with judgement in it: whether an operator can tell a short
list that means "two pages moved" from one that means "recentchanges could not
answer". Both look like a handful of titles; only the basis distinguishes them.
"""

runner = CliRunner()


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        202, json=payload, request=httpx.Request("POST", "http://wtbot/fetch/refresh")
    )


@pytest.fixture
def posted(monkeypatch):
    """Capture the request body and serve a canned reply."""
    captured: dict = {}
    payload: dict = {
        "plan": {
            "basis": "incremental",
            "reason": None,
            "titles": ["Page:Work.djvu/2"],
            "watermark": "2026-08-05T12:05:00Z",
            "changes": 1,
        },
        "enqueued": 1,
        "watermark": "2026-08-05T12:05:00Z",
    }

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _response(captured.get("reply", payload))

    monkeypatch.setattr(httpx, "post", fake_post)
    captured["reply"] = payload
    return captured


def test_the_command_posts_what_was_asked_for(posted) -> None:
    result = runner.invoke(
        create_app(),
        [
            "fetch-refresh",
            "--family",
            "mywikisource",
            "--code",
            "en",
            "--title-prefix",
            "Page:Work.djvu/",
            "--base-url",
            "http://wtbot:8000",
        ],
    )

    assert result.exit_code == 0, result.output
    assert posted["url"] == "http://wtbot:8000/fetch/refresh"
    assert posted["json"]["family"] == "mywikisource"
    assert posted["json"]["title_prefix"] == "Page:Work.djvu/"
    assert posted["json"]["dry_run"] is False
    assert "basis=incremental" in result.output
    assert "Page:Work.djvu/2" in result.output


def test_a_full_basis_reports_its_reason_and_that_nothing_advanced(posted) -> None:
    """The output an operator must not misread. A full pass reads no change
    stream, so it advances no watermark -- and without saying so, the next run
    being full again looks like a bug rather than the stated consequence."""
    posted["reply"] = {
        "plan": {
            "basis": "full",
            "reason": "watermark 2025-01-01T00:00:00+00:00 predates the oldest "
            "change the wiki still holds",
            "titles": ["Page:Work.djvu/1", "Page:Work.djvu/2"],
            "watermark": None,
            "changes": 0,
        },
        "enqueued": 2,
        "watermark": None,
    }

    result = runner.invoke(create_app(), ["fetch-refresh", "--base-url", "http://x"])

    assert result.exit_code == 0, result.output
    assert "basis=full" in result.output
    assert "predates the oldest change" in result.output
    assert "watermark unchanged" in result.output


def test_a_dry_run_says_so_without_claiming_a_watermark(posted) -> None:
    posted["reply"] = {
        "plan": {
            "basis": "incremental",
            "reason": None,
            "titles": [],
            "watermark": None,
            "changes": 0,
        },
        "enqueued": 0,
        "watermark": None,
    }

    result = runner.invoke(
        create_app(), ["fetch-refresh", "--dry-run", "--base-url", "http://x"]
    )

    assert result.exit_code == 0, result.output
    assert posted["json"]["dry_run"] is True
    assert "enqueued=0" in result.output
    # Not the full-pass message: nothing was enqueued because nothing was asked
    # to be, which is a different thing from a plan that could not advance.
    assert "watermark unchanged" not in result.output


def test_since_is_sent_as_an_iso_timestamp(posted) -> None:
    runner.invoke(
        create_app(),
        ["fetch-refresh", "--since", "2026-08-01", "--base-url", "http://x"],
    )

    assert posted["json"]["since"].startswith("2026-08-01T00:00:00")


def test_the_refresh_body_is_documented_in_openapi(client) -> None:
    """Pins requirement of the API contract: the request renders in Swagger as
    described fields with an example, not an opaque JSON blob, and the 202
    carries a typed schema rather than a bare dict."""
    spec = client.app.openapi()

    request_schema = spec["components"]["schemas"]["RefreshCreate"]
    assert set(request_schema["properties"]) == {
        "family",
        "code",
        "api_url",
        "since",
        "title_prefix",
        "dry_run",
    }
    assert all(
        field.get("description") for field in request_schema["properties"].values()
    )
    assert request_schema["examples"]

    operation = spec["paths"]["/fetch/refresh"]["post"]
    schema = operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("RefreshResult")
    assert spec["components"]["schemas"]["RefreshBasis"]["enum"] == [
        "incremental",
        "full",
    ]
