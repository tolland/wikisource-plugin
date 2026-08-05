import os

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=True,
    name="fetch-page",
)


@app.callback(invoke_without_command=True)
def fetch_page(
    ctx: typer.Context,
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

    if ctx.invoked_subcommand is not None:
        return

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
