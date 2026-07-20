"""Typer CLI for wtbot. Thin demonstration of the wiki-access seam from the
command line; the same WikiSettings injection works under tests and IntelliJ."""

import os

import typer

from wtbot.settings import WikiSettings

app = typer.Typer(
    help="wtbot — Wikisource editor backend",
    add_completion=False,
    no_args_is_help=True,
)


def _settings(
    family: str, code: str, api_url: str | None, ca_bundle: str | None
) -> WikiSettings:
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
    api_url: str | None = typer.Option(None, help="action API URL stored on the Site"),
    depth: int = typer.Option(
        1, help="expansion depth: 0=page only, 1=expand Index/File"
    ),
    base_url: str = typer.Option(
        lambda: os.environ.get("WTBOT_API_URL", "http://127.0.100.1:8000"),
        help="wtbot API base URL",
    ),
) -> None:
    """Enqueue a cache-fill via the wtbot API and report the result.

    This calls the running wtbot server, which creates a FetchRequest, drains it
    (the worker makes the pywikibot call), and writes the page back to SQLite.
    For Index: and File: pages depth=1 (the default) triggers full expansion:
    blob download + per-page child requests.
    """
    import httpx

    payload = {
        "title": title,
        "family": family,
        "code": code,
        "api_url": api_url,
        "depth": depth,
    }
    resp = httpx.post(f"{base_url.rstrip('/')}/fetch/", json=payload, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    req = data["request"]
    page = data.get("page")

    typer.echo(
        f"request #{req['pk']}  status={req['status']}  "
        f"progress={req['progress_done']}/{req['progress_total']}"
    )
    if page:
        typer.echo(f"  {page['title']}")
        typer.echo(f"  content_model = {page['content_model']}")
        typer.echo(f"  revid/sha1    = {page['revid']} / {page['sha1']}")
    if req.get("error_message"):
        typer.echo(f"  error = {req['error_message']}")


@app.command("import-svg-annotations")
def import_svg_annotations_cmd(
    blob_root: str = typer.Option(
        lambda: os.environ.get("WTBOT_BLOB_ROOT", "./blobs"),
        help="blob root containing the legacy annotations/*.svg documents",
    ),
    database_url: str | None = typer.Option(
        None, help="defaults to WTBOT_DATABASE_URL / sqlite:///database.db"
    ),
    dry_run: bool = typer.Option(
        False, help="report what would be imported, write nothing"
    ),
) -> None:
    """One-shot import of legacy per-page SVG annotation documents into the
    ScanAnnotation table.

    Reads blob_root/annotations/{page_pk}.svg (the pre-SQL storage), inserts
    every identifiable <rect> as a ScanAnnotation row, and reports anything
    it could not carry over (non-rect shapes, unsupported transforms). Rows
    that already exist are left alone, so re-running is safe. The SVG files
    are not deleted — remove the directory yourself once satisfied.
    """
    from pathlib import Path

    from wtbot.annotation_svg_import import import_svg_annotations
    from wtbot.db import create_db_engine, init_db

    url = database_url or os.environ.get("WTBOT_DATABASE_URL")
    engine = create_db_engine(url) if url else create_db_engine()
    init_db(engine)
    report = import_svg_annotations(engine, Path(blob_root), dry_run=dry_run)

    verb = "would import" if dry_run else "imported"
    typer.echo(f"{verb} {len(report.imported)} annotation(s)")
    for key in report.imported:
        typer.echo(f"  + {key}")
    if report.skipped_existing:
        typer.echo(f"skipped {len(report.skipped_existing)} already in the database:")
        for key in report.skipped_existing:
            typer.echo(f"  = {key}")
    if report.skipped_pages:
        typer.echo("skipped files with no matching Page row:")
        for name in report.skipped_pages:
            typer.echo(f"  ? {name}")
    for warning in report.warnings:
        typer.echo(f"  ! {warning}")


def run_cli() -> None:
    app()


if __name__ == "__main__":
    run_cli()
