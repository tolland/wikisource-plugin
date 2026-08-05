import os
from datetime import datetime

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=False,
    name="fetch-refresh",
)


@app.callback(invoke_without_command=True)
def fetch_refresh(
    ctx: typer.Context,
    family: str = typer.Option("wikisource"),
    code: str = typer.Option("en"),
    api_url: str | None = typer.Option(None, help="action API URL stored on the Site"),
    title_prefix: str | None = typer.Option(
        None,
        help=(
            "Narrow to one work, e.g. 'Page:Some_book.djvu/'. With a prefix, "
            "titles not held locally are taken too -- that is how a partially "
            "transcribed index grows."
        ),
    ),
    since: datetime | None = typer.Option(
        None,
        formats=["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"],
        help="Override the site's stored watermark, e.g. 2026-08-01.",
    ),
    dry_run: bool = typer.Option(
        False, help="Plan only: print what would be refetched, advance nothing."
    ),
    base_url: str = typer.Option(
        lambda: os.environ.get("WTBOT_API_URL", "http://127.0.100.1:8000"),
        help="wtbot API base URL",
    ),
) -> None:
    """Refetch only what moved upstream, via ``list=recentchanges``.

    Not a second fetch mechanism: it plans a shorter list of titles and hands
    them to the same queue ``fetch-page`` uses. Read the *basis* in the output
    before believing a short list -- ``full`` means recentchanges could not
    answer (no watermark, or one older than the wiki still remembers) and every
    known title is a candidate, which is a different statement from "two pages
    moved".
    """
    if ctx.invoked_subcommand is not None:
        return

    import httpx

    payload = {
        "family": family,
        "code": code,
        "api_url": api_url,
        "title_prefix": title_prefix,
        "since": since.isoformat() if since else None,
        "dry_run": dry_run,
    }
    resp = httpx.post(
        f"{base_url.rstrip('/')}/fetch/refresh", json=payload, timeout=300.0
    )
    resp.raise_for_status()
    data = resp.json()
    plan = data["plan"]

    typer.echo(
        f"basis={plan['basis']}  changes={plan['changes']}  "
        f"titles={len(plan['titles'])}  enqueued={data['enqueued']}"
    )
    if plan.get("reason"):
        typer.echo(f"  reason: {plan['reason']}")
    for title in plan["titles"]:
        typer.echo(f"  {title}")
    if data.get("watermark"):
        typer.echo(f"  watermark now {data['watermark']}")
    elif not dry_run:
        # A full pass reads no change stream, so it advances nothing; saying so
        # beats leaving the operator to wonder why the next run is full again.
        typer.echo("  watermark unchanged (a full pass claims no position)")
