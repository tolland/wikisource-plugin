from datetime import datetime, timedelta
from typing import Annotated

import pytimeparse
import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api, get_context, get_label
from wtbot.timeutil import as_utc, utcnow

app = TyperDI(
    no_args_is_help=False,
    name="refresh",
)


def parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    if seconds := pytimeparse.parse(value):
        return utcnow() - timedelta(seconds=seconds)
    # A bare '2026-08-01' parses naive; the option documents itself as UTC,
    # so say so rather than shipping a tz-less timestamp to the server.
    return as_utc(datetime.fromisoformat(value))


@app.callback(invoke_without_command=True)
def fetch_refresh(
    ctx: typer.Context = Depends(get_context),
    since: datetime = typer.Option(
        # formats=["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"],
        # formats=None,
        help="Required inclusive start date/time in UTC, e.g. 2026-08-01. No server cursor is stored.",
        parser=parse_since,
    ),
    title_prefix: Annotated[
        str | None,
        typer.Option(
            help=(
                "Narrow to one work, e.g. 'Page:Some_book.djvu/'. With a prefix, "
                "titles not held locally are taken too -- that is how a partially "
                "transcribed index grows."
            ),
        ),
    ] = None,
    dry_run: bool = typer.Option(
        False, help="Plan only: print what would be refetched, enqueue nothing."
    ),
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Plan a refetch of whatever moved upstream, via ``list=recentchanges``.

    Enqueues; ``wtbot drain`` fetches.

    Not a second fetch mechanism: it plans a shorter list of titles and hands
    them to the same queue ``fetch-page`` uses. Read the *basis* in the output
    before believing a short list -- ``full`` means recentchanges could not
    answer (--since is older than the wiki still remembers) and every
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
            "since": since.isoformat() if since is not None else None,
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
    if dry_run:
        typer.echo("  dry run: nothing enqueued")
    if not dry_run and data["enqueued"]:
        typer.echo("  run `wtbot drain` to fetch them")
