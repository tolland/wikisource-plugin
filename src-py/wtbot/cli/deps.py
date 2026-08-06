import os
from dataclasses import dataclass
from typing import Annotated, Any

import typer

"""Shared CLI options, as TyperDI dependencies.

Every command talks to the same API and most of them address the same wiki, so
``--base-url`` and ``--label`` were being redeclared per command along with the
httpx call and its error handling. A Typer *callback* is the other way to share
them, but a callback's values arrive on ``ctx.parent.params``, so each command
then digs them back out by name -- the option is declared in one place and
retrieved by string in another.

TyperDI inverts that: a dependency declares the options it needs, and any
command that depends on it gets them merged into its own signature (so they
still appear in ``--help`` and are still passed on that command's own command
line). The command receives a built object rather than loose strings.

    @app.command()
    def show(api: ApiClient = Depends(get_api)) -> None:
        typer.echo(api.get("/fetch/queue"))

There is deliberately no global state and no ctx digging here.
"""

DEFAULT_BASE_URL = "http://127.0.100.1:8000"

#: Generous by default: a drain of a throttled fan-out legitimately runs for
#: minutes, and a timeout mid-drain looks like a server fault.
DEFAULT_TIMEOUT = 3600.0


@dataclass(frozen=True)
class ApiClient:
    """The wtbot API, with the error handling every command wants.

    A failed call prints the server's ``detail`` -- which is where the useful
    message lives ("no site labelled 'lcoal'. Registered: local, en.wikisource")
    -- and exits non-zero, rather than raising an httpx traceback at someone
    who typed a label wrong.
    """

    base_url: str
    timeout: float = DEFAULT_TIMEOUT

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def get(self, path: str, **params: Any) -> Any:
        import httpx

        return self._result(
            httpx.get(self._url(path), params=params or None, timeout=self.timeout)
        )

    def get_optional(self, path: str) -> Any | None:
        """A GET whose 404 is an answer rather than an error -- "this site has
        no credential" is a fact worth printing, not a failure to report."""
        import httpx

        response = httpx.get(self._url(path), timeout=self.timeout)
        if response.status_code == 404:
            return None
        return self._result(response)

    def post(self, path: str, payload: dict | None = None) -> Any:
        import httpx

        return self._result(
            httpx.post(self._url(path), json=payload, timeout=self.timeout)
        )

    def put(self, path: str, payload: dict | None = None) -> Any:
        import httpx

        return self._result(
            httpx.put(self._url(path), json=payload, timeout=self.timeout)
        )

    def delete(self, path: str) -> Any:
        import httpx

        return self._result(httpx.delete(self._url(path), timeout=self.timeout))

    @staticmethod
    def _result(response) -> Any:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:  # noqa: BLE001 - a non-JSON error body is still an error
                detail = response.text
            typer.secho(f"{response.status_code}: {detail}", fg="red", err=True)
            raise typer.Exit(1)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def get_api(
    base_url: Annotated[
        str,
        typer.Option(
            "--base-url",
            envvar="WTBOT_API_URL",
            show_envvar=False,
            help="wtbot API base URL",
        ),
    ] = DEFAULT_BASE_URL,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = DEFAULT_TIMEOUT,
) -> ApiClient:
    """Dependency: the API client, with --base-url/--timeout on the command."""
    return ApiClient(base_url=base_url, timeout=timeout)


def get_label(
    label: Annotated[
        str,
        typer.Option(
            "--label",
            envvar="WTBOT_SITE_LABEL",
            show_envvar=False,
            help="Registered site to act on (see `wtbot site list`).",
        ),
    ] = os.environ.get("WTBOT_SITE_LABEL", ""),
) -> str:
    """Dependency: the site label, required but settable from the environment.

    Not a plain required option, because a session usually works against one
    wiki: ``WTBOT_SITE_LABEL=local`` makes every command in that shell target
    it, while ``--label`` still wins for a one-off against another.
    """
    if not label:
        typer.secho(
            "no site given: pass --label or set WTBOT_SITE_LABEL "
            "(`wtbot site list` shows the registered ones)",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)
    return label
