import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

"""The CLI side of the push queue: `sync batches`/`batch`/`approve`/`push`/
`abort`, wrapping the same `/sync/batches` HTTP contract the viewer drives.

The judgement worth pinning is in `push`: which row it reports (the API
returns the whole batch, not the row it just acted on, so the command has to
diff two snapshots to say which one), and that `--all` stops the moment a row
does not push cleanly rather than grinding through a batch built on an
assumption that just proved wrong.
"""

runner = CliRunner()


def _row(
    pk: int,
    status: str,
    *,
    title: str = "Page:Foo.djvu/1",
    result_revid=None,
    error=None,
) -> dict:
    return {
        "pk": pk,
        "page_number": pk,
        "target_title": title,
        "intent": "update",
        "status": status,
        "base_revid": 10,
        "pre_push_target_revid": None,
        "result_revid": result_revid,
        "error_message": error,
        "body_length": 42,
    }


def _batch(pk: int, status: str, promotions: list[dict], **extra) -> dict:
    counts: dict[str, int] = {}
    for row in promotions:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "pk": pk,
        "label": None,
        "status": status,
        "source_site": "upstream",
        "target_site": "local",
        "source_index_title": "Page:Foo.djvu/1",
        "target_index_title": "Page:Foo.djvu/1",
        "approved_by": "reviewer",
        "work_pk": None,
        "counts": counts,
        "remaining": sum(1 for row in promotions if row["status"] == "staged"),
        "promotions": promotions,
        **extra,
    }


@pytest.fixture
def api(monkeypatch):
    """A stand-in wtbot API: canned GETs, a queue of POST replies consumed
    in call order."""
    calls: dict = {"gets": [], "posts": [], "get_reply": None, "post_replies": []}

    def fake_get(url, params=None, timeout=None):
        calls["gets"].append(url)
        return httpx.Response(
            200, json=calls["get_reply"], request=httpx.Request("GET", url)
        )

    def fake_post(url, json=None, timeout=None):
        calls["posts"].append((url, json))
        body = calls["post_replies"].pop(0)
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_batches_lists_every_run(api):
    api["get_reply"] = [_batch(1, "draft", [_row(1, "staged")])]

    result = runner.invoke(create_app(), ["sync", "batches"])

    assert result.exit_code == 0, result.output
    assert "#1" in result.output
    assert "draft" in result.output


def test_batch_shows_every_row(api):
    api["get_reply"] = _batch(
        1, "approved", [_row(1, "pushed", result_revid=99), _row(2, "staged")]
    )
    result = runner.invoke(create_app(), ["sync", "batch", "1"])
    assert result.exit_code == 0, result.output
    assert "approved by reviewer" in result.output
    assert "revid 99" in result.output
    assert "1 still staged" in result.output


def test_approve_posts_the_name(api):
    api["post_replies"] = [_batch(1, "approved", [_row(1, "staged")])]
    result = runner.invoke(create_app(), ["sync", "approve", "1", "--by", "reviewer"])
    assert result.exit_code == 0, result.output
    url, payload = api["posts"][0]
    assert url.endswith("/sync/batches/1/approve")
    assert payload == {"approved_by": "reviewer"}


def test_push_reports_the_row_it_pushed(api):
    """The row the diff picks out, not just 'something happened'."""
    api["get_reply"] = _batch(1, "approved", [_row(1, "staged")])
    api["post_replies"] = [
        _batch(1, "complete", [_row(1, "pushed", result_revid=4242)])
    ]

    result = runner.invoke(create_app(), ["sync", "push", "1"])

    assert result.exit_code == 0, result.output
    assert "#1" in result.output
    assert "pushed" in result.output
    assert "revid 4242" in result.output
    url, payload = api["posts"][0]
    assert url.endswith("/sync/batches/1/push")
    assert payload == {"force": False}


def test_push_promotion_names_the_row_explicitly(api):
    api["get_reply"] = _batch(1, "approved", [_row(1, "staged"), _row(2, "staged")])
    api["post_replies"] = [
        _batch(1, "running", [_row(1, "staged"), _row(2, "pushed", result_revid=7)])
    ]

    result = runner.invoke(create_app(), ["sync", "push", "1", "--promotion", "2"])

    assert result.exit_code == 0, result.output
    _, payload = api["posts"][0]
    assert payload == {"force": False, "promotion_pk": 2}
    assert "#2" in result.output


def test_push_all_stops_the_moment_a_row_does_not_push_cleanly(api):
    api["get_reply"] = _batch(1, "approved", [_row(1, "staged"), _row(2, "staged")])
    api["post_replies"] = [
        _batch(1, "running", [_row(1, "pushed", result_revid=1), _row(2, "staged")]),
        _batch(
            1,
            "partial",
            [
                _row(1, "pushed", result_revid=1),
                _row(2, "conflict", error="the target moved"),
            ],
        ),
    ]

    result = runner.invoke(create_app(), ["sync", "push", "1", "--all"])

    assert result.exit_code == 0, result.output
    assert len(api["posts"]) == 2  # stopped, did not try a third row
    assert "did not push cleanly" in result.output
    assert "the target moved" in result.output


def test_push_all_with_nothing_staged_pushes_nothing(api):
    api["get_reply"] = _batch(1, "complete", [_row(1, "pushed", result_revid=1)])

    result = runner.invoke(create_app(), ["sync", "push", "1", "--all"])

    assert result.exit_code == 0, result.output
    assert not api["posts"]
    assert "no staged rows left" in result.output


def test_push_refuses_both_a_row_and_all(api):
    result = runner.invoke(
        create_app(), ["sync", "push", "1", "--promotion", "2", "--all"]
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_abort_posts_and_reports(api):
    api["post_replies"] = [_batch(1, "aborted", [_row(1, "skipped")])]
    result = runner.invoke(create_app(), ["sync", "abort", "1"])
    assert result.exit_code == 0, result.output
    assert api["posts"][0][0].endswith("/sync/batches/1/abort")
    assert "aborted" in result.output
