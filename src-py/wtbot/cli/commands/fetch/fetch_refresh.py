from datetime import datetime

import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api, get_context, get_label

app = TyperDI(
    no_args_is_help=False,
    name="refresh",
)


@app.callback(invoke_without_command=True)
def fetch_refresh(
    ctx: typer.Context = Depends(get_context),
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
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Plan a refetch of whatever moved upstream, via ``list=recentchanges``.

    Enqueues; ``wtbot drain`` fetches.

    Not a second fetch mechanism: it plans a shorter list of titles and hands
    them to the same queue ``fetch-page`` uses. Read the *basis* in the output
    before believing a short list -- ``full`` means recentchanges could not
    answer (no watermark, or one older than the wiki still remembers) and every
    known title is a candidate, which is a different statement from "two pages
    moved".
    """
    if ctx.invoked_subcommand is not None:
        return

    data = api.post(
        "/fetch/refresh",
        {
            "label": label,
            "title_prefix": title_prefix,
            "since": since.isoformat() if since else None,
            "dry_run": dry_run,
        },
    )
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
    if not dry_run and data["enqueued"]:
        typer.echo("  run `wtbot drain` to fetch them")
