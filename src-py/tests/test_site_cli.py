"""The site and site-credential commands, and the shared TyperDI options.

Two things worth pinning. First, that registering a wiki says what is still
missing: an operator who does not know a credential is optional, and does not
know why, is the person who ends up wondering why commits fail. Second, that
the dependency-injected options are really on each command -- a shared option
that silently stops being accepted is worse than one that was never shared.
"""

import httpx
import pytest
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app

runner = CliRunner()

SITE = {
    "pk": 1,
    "label": "local",
    "family": "mywikisource",
    "code": "en",
    "api_url": "https://wikisource-debian-13.lan/w/api.php",
    "articlepath": "/wiki/$1",
}
CREDENTIAL = {
    "site_pk": 1,
    "username": "Admin",
    "bot_name": "wtbot",
    "password": "secret",
    "updated_at": "2026-08-06T12:00:00",
}
DELETE_PLAN = {
    "site_pk": 1,
    "label": "local",
    "family": "mywikisource",
    "code": "en",
    "counts": [
        {"table": "revision", "rows": 40},
        {"table": "page", "rows": 12},
        {"table": "site", "rows": 1},
    ],
}


@pytest.fixture
def api(monkeypatch):
    """A stand-in wtbot API. `routes` maps path -> response body; anything
    unlisted 404s, which is how "no credential yet" is expressed."""
    calls: dict = {
        "routes": {"/sites/by-label/local": SITE, "/sites/": [SITE]},
        "posted": [],
        "put": [],
        "deleted": [],
    }

    def _response(method: str, url: str, body=None):
        path = url.split("8000", 1)[-1] if "8000" in url else url
        for known, payload in calls["routes"].items():
            if path.endswith(known):
                return httpx.Response(
                    200, json=payload, request=httpx.Request(method, url)
                )
        return httpx.Response(
            404,
            json={"detail": f"not found: {path}"},
            request=httpx.Request(method, url),
        )

    def fake_get(url, params=None, timeout=None):
        return _response("GET", url)

    def fake_post(url, json=None, timeout=None):
        calls["posted"].append((url, json))
        return httpx.Response(
            201, json={**SITE, **(json or {})}, request=httpx.Request("POST", url)
        )

    def fake_put(url, json=None, timeout=None):
        calls["put"].append((url, json))
        return httpx.Response(
            200,
            json={**CREDENTIAL, **(json or {})},
            request=httpx.Request("PUT", url),
        )

    def fake_delete(url, timeout=None):
        calls["deleted"].append(url)
        return httpx.Response(
            200, json=DELETE_PLAN, request=httpx.Request("DELETE", url)
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "put", fake_put)
    monkeypatch.setattr(httpx, "delete", fake_delete)
    return calls


def test_site_add_registers_and_says_what_is_missing(api):
    result = runner.invoke(
        create_app(),
        [
            "site",
            "add",
            "--label",
            "local",
            "--family",
            "mywikisource",
            "--code",
            "en",
            "--api-url",
            "https://wikisource-debian-13.lan/w/api.php",
        ],
    )

    assert result.exit_code == 0, result.output
    url, payload = api["posted"][0]
    assert url.endswith("/sites/")
    assert payload["label"] == "local"
    assert payload["api_url"] == "https://wikisource-debian-13.lan/w/api.php"
    # The blocker, stated as a blocker: this wiki is registered but cannot be
    # used until it can log in.
    assert "will be refused" in result.output
    assert "site-credential add" in result.output
    assert "WTBOT_ALLOW_ANONYMOUS" in result.output


def test_site_add_can_take_the_credential_in_the_same_step(api):
    """Registration and the account are one operation, because a wiki without
    one is registered and unusable."""
    result = runner.invoke(
        create_app(),
        [
            "site",
            "add",
            "--label",
            "local",
            "--family",
            "mywikisource",
            "--code",
            "en",
            "--username",
            "Admin",
            "--password",
            "changeme",
            "--bot-password-suffix",
            "wtbot",
        ],
    )

    assert result.exit_code == 0, result.output
    url, payload = api["put"][0]
    assert url.endswith("/sites/1/credential")
    assert payload["username"] == "Admin"
    assert payload["bot_name"] == "wtbot"
    assert "logs in as Admin@wtbot" in result.output
    assert "no credential" not in result.output


def test_site_delete_without_force_is_the_dry_run(api):
    """No --force means show the consequences and touch nothing -- the preview
    IS the default, not an option someone has to know to ask for."""
    api["routes"]["/sites/1/delete-plan"] = DELETE_PLAN

    result = runner.invoke(create_app(), ["site", "delete", "local"])

    assert result.exit_code == 0, result.output
    assert api["deleted"] == [], "no DELETE may be issued without --force"
    assert "would delete" in result.output
    assert "revision" in result.output and "40" in result.output
    assert "nothing deleted" in result.output
    assert "--force" in result.output


def test_site_delete_with_force_deletes_and_reports_what_went(api):
    result = runner.invoke(create_app(), ["site", "delete", "local", "--force"])

    assert result.exit_code == 0, result.output
    assert len(api["deleted"]) == 1
    assert api["deleted"][0].endswith("/sites/1")
    assert "deleted from local (mywikisource:en)" in result.output
    assert "page" in result.output and "12" in result.output
    assert "would delete" not in result.output


def test_credential_add_targets_the_site_by_label(api):
    result = runner.invoke(
        create_app(),
        [
            "site-credential",
            "add",
            "--label",
            "local",
            "--username",
            "Admin",
            "--password",
            "changeme",
            "--bot-password-suffix",
            "wtbot",
        ],
    )

    assert result.exit_code == 0, result.output
    url, payload = api["put"][0]
    assert url.endswith("/sites/1/credential")
    assert payload == {
        "username": "Admin",
        "password": "changeme",
        "bot_name": "wtbot",
    }
    assert "Admin@wtbot" in result.output


def test_credential_show_never_prints_the_password(api):
    api["routes"]["/sites/1/credential"] = CREDENTIAL

    result = runner.invoke(
        create_app(), ["site-credential", "show", "--label", "local"]
    )

    assert result.exit_code == 0, result.output
    assert "Admin@wtbot" in result.output
    assert "secret" not in result.output


def test_credential_show_reports_absence_as_a_fact_not_an_error(api):
    """A site with no credential is a supported configuration, so this is an
    answer with exit code 0 -- not a 404 traced at the operator."""
    result = runner.invoke(
        create_app(), ["site-credential", "show", "--label", "local"]
    )

    assert result.exit_code == 0, result.output
    assert "no credential" in result.output
    assert "commits do not" in result.output


def test_a_missing_label_is_a_usage_error_naming_the_way_out(api):
    result = runner.invoke(create_app(), ["site-credential", "show"])

    assert result.exit_code == 2
    assert "--label" in result.output
    assert "WTBOT_SITE_LABEL" in result.output


def test_the_label_can_come_from_the_environment(api, monkeypatch):
    """A session usually works against one wiki; --label stays available for
    the one-off against another."""
    monkeypatch.setenv("WTBOT_SITE_LABEL", "local")

    result = runner.invoke(create_app(), ["site-credential", "show"])

    assert result.exit_code == 0, result.output
    assert "local" in result.output


def test_an_api_error_is_reported_without_a_traceback(api, monkeypatch):
    """The failure mode the shared client exists for: the server's `detail`
    is the useful part, and an httpx traceback buries it."""

    def failing_get(url, params=None, timeout=None):
        return httpx.Response(
            404,
            json={"detail": "no site labelled 'nope'. Registered: local."},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", failing_get)

    result = runner.invoke(create_app(), ["site", "show", "nope"])

    assert result.exit_code == 1
    assert "no site labelled 'nope'" in result.output
    assert "Registered: local." in result.output
    assert "Traceback" not in result.output


def test_api_location_is_global_and_command_dependencies_remain_local():
    root_help = runner.invoke(create_app(), ["--help"])
    assert root_help.exit_code == 0
    assert "--base-url" in root_help.output

    for argv in (
        ["site", "add", "--help"],
        ["site-credential", "add", "--help"],
        ["fetch-page", "--help"],
        ["drain", "--help"],
    ):
        result = runner.invoke(create_app(), argv)
        assert result.exit_code == 0, argv
        assert "--base-url" not in result.output, argv

    for argv in (["site-credential", "add", "--help"], ["fetch-page", "--help"]):
        result = runner.invoke(create_app(), argv)
        assert "--label" in result.output, argv
