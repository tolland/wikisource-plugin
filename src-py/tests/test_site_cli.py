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
    "host": None,
}
CREDENTIAL = {
    "site_pk": 1,
    "username": "Admin",
    "bot_name": "wtbot",
    "password": "secret",
    "updated_at": "2026-08-06T12:00:00",
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
        return httpx.Response(204, request=httpx.Request("DELETE", url))

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
    # The follow-up an operator needs, at the moment it can be acted on...
    assert "site-credential add" in result.output
    # ...and accurately: reads do not need it.
    assert "reads work anonymously" in result.output


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


def test_shared_options_are_present_on_every_command_that_depends_on_them():
    """The injected options must really reach each command's own parser."""
    for argv in (
        ["site", "add", "--help"],
        ["site-credential", "add", "--help"],
        ["fetch-page", "--help"],
        ["drain", "--help"],
    ):
        result = runner.invoke(create_app(), argv)
        assert result.exit_code == 0, argv
        assert "--base-url" in result.output, argv

    for argv in (["site-credential", "add", "--help"], ["fetch-page", "--help"]):
        result = runner.invoke(create_app(), argv)
        assert "--label" in result.output, argv
