import re

import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

"""The drain CLI.

``fetch-page`` and ``fetch-refresh`` queue work; this is the command that
performs it. The judgement worth testing is in the reporting: a drain that
stopped early must not read like one that finished, or an operator walks away
from a half-fetched book.
"""

runner = CliRunner()

_QUEUE = {
    "counts": {"pending": 3, "done": 12},
    "pending": 3,
    "total": 15,
    "oldest_pending_at": "2026-08-06T09:00:00Z",
}
_COMPLETE = {
    "handled": 3,
    "passes": 2,
    "remaining": 0,
    "stop_reason": "queue_empty",
    "complete": True,
}


@pytest.fixture
def api(monkeypatch):
    """Capture the calls and serve canned replies."""
    calls: dict = {"queue": _QUEUE, "drain": _COMPLETE}

    def fake_get(url, params=None, timeout=None):
        calls["get_url"] = url
        return httpx.Response(
            200, json=calls["queue"], request=httpx.Request("GET", url)
        )

    def fake_post(url, json=None, timeout=None):
        calls["post_url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return httpx.Response(
            200, json=calls["drain"], request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_drain_posts_and_reports(api):
    result = runner.invoke(create_app(), ["--base-url", "http://wtbot:8000", "drain"])

    assert result.exit_code == 0, result.output
    assert api["post_url"] == "http://wtbot:8000/fetch/drain"
    assert api["json"] == {"batch": 200, "max_passes": 100}
    assert "drained 3 request(s) in 2 pass(es); 0 remaining" in result.output


def test_base_url_is_not_accepted_after_the_subcommand(api):
    result = runner.invoke(
        create_app(), ["drain", "--base-url", "http://wtbot:8000", "--status"]
    )

    assert result.exit_code == 2
    # remove any ANSI escape codes that appoear in GitHub Actions terminal
    reaesc = re.compile(r"\x1b[^m]*m")
    assert "No such option: --base-url" in reaesc.sub("", result.output)
    assert "get_url" not in api


def test_drain_passes_its_bounds_through(api):
    result = runner.invoke(
        create_app(),
        ["--base-url", "http://w:8000", "drain", "--batch", "25", "--max-passes", "4"],
    )

    assert result.exit_code == 0, result.output
    assert api["json"] == {"batch": 25, "max_passes": 4}


def test_an_incomplete_drain_says_so(api):
    """The output an operator must not misread. Work is still queued, and
    reporting only 'drained 2' would read as done."""
    api["drain"] = {
        "handled": 2,
        "passes": 100,
        "remaining": 40,
        "stop_reason": "max_passes",
        "complete": False,
    }

    result = runner.invoke(create_app(), ["--base-url", "http://w:8000", "drain"])

    assert result.exit_code == 0, result.output
    assert "40 remaining" in result.output
    assert "incomplete" in result.output
    assert "max_passes" in result.output
    assert "run again to continue" in result.output


def test_a_rate_limited_drain_says_not_to_just_run_again(api):
    """The one incomplete case where "run again" is wrong advice: the wiki
    refused us for going too fast, so going again asks for the same refusal."""
    api["drain"] = {
        "handled": 12,
        "passes": 1,
        "remaining": 88,
        "stop_reason": "rate_limited",
        "complete": False,
        "retry_after": 45.0,
    }

    result = runner.invoke(create_app(), ["--base-url", "http://w:8000", "drain"])

    assert result.exit_code == 0, result.output
    assert "rate-limited" in result.output
    assert "45s" in result.output
    assert "WTBOT_WIKI_READ_THROTTLE" in result.output
    assert "run again to continue" not in result.output


def test_status_reports_the_queue_without_draining(api):
    result = runner.invoke(
        create_app(), ["--base-url", "http://wtbot:8000", "drain", "--status"]
    )

    assert result.exit_code == 0, result.output
    assert api["get_url"] == "http://wtbot:8000/fetch/queue"
    assert "post_url" not in api, "--status must not start a drain"
    assert "pending=3" in result.output
    assert "done=12" in result.output
    assert "2026-08-06T09:00:00Z" in result.output


def test_the_timeout_allows_for_a_throttled_fan_out(api):
    """A book's worth of throttled fetches takes minutes; a default httpx
    timeout would abort the drain mid-run and look like a server fault."""
    runner.invoke(create_app(), ["--base-url", "http://w:8000", "drain"])
    assert api["timeout"] >= 600
