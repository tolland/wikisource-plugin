import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

"""`wtbot vfs delete`: a dry run unless --force, like `wtbot site delete`."""

runner = CliRunner()

PATH = "/mywikisource/en/(Main)/Book/Foo"
RESULT = {
    "path": PATH,
    "recursive": False,
    "dry_run": True,
    "deleted_paths": [PATH],
}


@pytest.fixture
def sent(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_delete(url, params=None, timeout=None):
        calls.append({"url": url, "params": params})
        return httpx.Response(
            200,
            json=RESULT | {"dry_run": params["dry_run"]},
            request=httpx.Request("DELETE", url),
        )

    monkeypatch.setattr(httpx, "delete", fake_delete)
    return calls


def test_delete_without_force_is_a_dry_run(sent):
    result = runner.invoke(create_app(), ["vfs", "delete", PATH])

    assert result.exit_code == 0, result.output
    assert sent[0]["url"].endswith("/vfs/node")
    assert sent[0]["params"] == {
        "path": PATH,
        "recursive": False,
        "discard_local_edits": False,
        "dry_run": True,
    }
    assert "would delete 1 title(s)" in result.output
    assert "nothing deleted" in result.output


def test_delete_force_recursive(sent):
    result = runner.invoke(
        create_app(), ["vfs", "delete", PATH, "-r", "--discard-local-edits", "--force"]
    )

    assert result.exit_code == 0, result.output
    assert sent[0]["params"] == {
        "path": PATH,
        "recursive": True,
        "discard_local_edits": True,
        "dry_run": False,
    }
    assert "deleted 1 title(s)" in result.output
    assert "nothing deleted" not in result.output
