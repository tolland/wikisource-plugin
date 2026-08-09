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
