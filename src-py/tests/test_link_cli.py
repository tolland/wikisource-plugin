import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

"""The retraction commands, where picking the wrong one is expensive.

`unpair` and `unpair-revision` differ in what survives, not in how much they
delete: `unpair` also discards the claim that the two pages are the same page,
and everything that hangs off it. The CLI has to make the narrow one reachable
and has to route each command to the endpoint that does what its help says --
these tests pin the second half, which no amount of prose can.
"""

runner = CliRunner()


@pytest.fixture
def api(monkeypatch):
    """A stand-in wtbot API recording what each command deleted."""
    calls: dict = {"deleted": []}

    def fake_delete(url, timeout=None):
        calls["deleted"].append(url)
        path = url.split("/links", 1)[-1]
        if path.endswith("/rungs"):
            body = {"pairing": 4, "rungs_removed": 3}
        elif path.startswith("/pairs/"):
            body = {"deleted": 4, "rungs_removed": 3}
        else:
            body = {"deleted": 11, "pairing": 4}
        return httpx.Response(200, json=body, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(httpx, "delete", fake_delete)
    return calls


def test_unpair_revision_retracts_one_rung(api):
    result = runner.invoke(create_app(), ["link", "unpair-revision", "11"])

    assert result.exit_code == 0, result.output
    assert api["deleted"][0].endswith("/links/11")
    # The reassurance is the point of the command: the pairing is still there.
    assert "pairing 4 kept" in result.output


def test_unpair_revision_can_clear_a_whole_ladder(api):
    result = runner.invoke(create_app(), ["link", "unpair-revision", "--pair", "4"])

    assert result.exit_code == 0, result.output
    assert api["deleted"][0].endswith("/links/pairs/4/rungs")
    assert "retracted 3 rung(s)" in result.output
    assert "pairing 4 kept" in result.output


def test_unpair_revision_refuses_an_ambiguous_target(api):
    """A rung pk and a pairing pk name different things, and the command that
    guessed which was meant would guess wrong on the day it mattered."""
    result = runner.invoke(
        create_app(), ["link", "unpair-revision", "11", "--pair", "4"]
    )

    assert result.exit_code == 2
    assert api["deleted"] == []


def test_unpair_revision_requires_a_target(api):
    result = runner.invoke(create_app(), ["link", "unpair-revision"])

    assert result.exit_code == 2
    assert api["deleted"] == []


def test_unpair_still_removes_the_pairing_itself(api):
    """The wide command is unchanged -- `unpair-revision` is an addition, not a
    redefinition."""
    result = runner.invoke(create_app(), ["link", "unpair", "4"])

    assert result.exit_code == 0, result.output
    assert api["deleted"][0].endswith("/links/pairs/4")
    assert "removed pairing 4" in result.output


@pytest.fixture
def revision_api(monkeypatch):
    posts = []

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "local_title": "Page:Book/1",
                "remote_title": "Page:Other/1",
                "local_site": "local",
                "remote_site": "upstream",
                "local": [
                    {"revid": 12, "is_head": True},
                    {"revid": 11, "is_head": False},
                ],
                "remote": [{"revid": 902, "is_head": True}],
            },
            request=httpx.Request("GET", url),
        )

    def fake_post(url, json=None, **kwargs):
        posts.append((url, json))
        return httpx.Response(201, json={"pk": 8}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return posts


def test_explicit_revision_link_defaults_to_read_only_preview(revision_api):
    result = runner.invoke(
        create_app(),
        ["link", "revision", "4", "--local-revid", "11", "--remote-revid", "902"],
    )
    assert result.exit_code == 0, result.output
    assert revision_api == []
    assert "Dry run: nothing written" in result.output
    assert "local: Page:Book/1 @ 11" in result.output
    assert "upstream: Page:Other/1 @ 902 (cached HEAD)" in result.output


def test_explicit_revision_link_force_records_exact_wiki_ids(revision_api):
    result = runner.invoke(
        create_app(),
        [
            "link",
            "revision",
            "4",
            "--local-revid",
            "11",
            "--remote-revid",
            "902",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(revision_api) == 1
    url, payload = revision_api[0]
    assert url.endswith("/links/pairs/4/rungs")
    assert payload == {
        "local_revid": 11,
        "remote_revid": 902,
        "origin": "manual",
        "force": True,
    }
    assert "no wiki edits made" in result.output


@pytest.mark.parametrize("force", [[], ["--force"]])
@pytest.mark.parametrize("local,remote", [(999, 902), (11, 999)])
def test_explicit_revision_link_rejects_uncached_or_wrong_page_revision(
    revision_api, force, local, remote
):
    result = runner.invoke(
        create_app(),
        [
            "link",
            "revision",
            "4",
            "--local-revid",
            str(local),
            "--remote-revid",
            str(remote),
            *force,
        ],
    )
    assert result.exit_code == 1
    assert "not cached" in result.output
    assert revision_api == []
