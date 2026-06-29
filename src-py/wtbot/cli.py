"""Typer CLI for wtbot. Thin demonstration of the wiki-access seam from the
command line; the same WikiSettings injection works under tests and IntelliJ."""

from __future__ import annotations

import typer

from wtbot.settings import WikiSettings

app = typer.Typer(
    help="wtbot — Wikisource editor backend",
    add_completion=False,
    no_args_is_help=True,
)


def _settings(family: str, code: str, api_url: str | None, ca_bundle: str | None) -> WikiSettings:
    return WikiSettings(family=family, code=code, api_url=api_url, ca_bundle=ca_bundle)


@app.command("show-config")
def show_config(
    family: str = typer.Option("wikisource"),
    code: str = typer.Option("en"),
    api_url: str | None = typer.Option(None),
    ca_bundle: str | None = typer.Option(None),
) -> None:
    """Print the resolved WikiSettings (no network)."""
    typer.echo(_settings(family, code, api_url, ca_bundle))


@app.command("fetch-page")
def fetch_page(
    title: str = typer.Argument(..., help="e.g. Index:Some_book.djvu"),
    family: str = typer.Option("wikisource"),
    code: str = typer.Option("en"),
    api_url: str | None = typer.Option(None, help="action API URL; preferred"),
    ca_bundle: str | None = typer.Option(None, help="CA cert for a self-signed wiki"),
) -> None:
    """Fetch one page from the wiki and print its identity (live network)."""
    from wtbot.wiki.client import get_wiki_client
    from wtbot.wiki.dispatch import classify_remote

    client = get_wiki_client(_settings(family, code, api_url, ca_bundle))
    page = client.get_page(title)
    handling = classify_remote(page)
    typer.echo(
        f"{page.title}\n"
        f"  content_model = {page.content_model}\n"
        f"  handling      = {handling.value}\n"
        f"  revid/sha1    = {page.revid} / {page.sha1}"
    )


def run_cli() -> None:
    app()


if __name__ == "__main__":
    run_cli()
