from typing import Annotated

import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="sync",
    help="Compare a work across two sites and report what a sync would do.",
)

"""``wtbot sync report --from Index:X [--to Index:Y]``.

The happy path end to end, and deliberately read-only. It answers the question
that comes before any push -- "what would this actually change, and is the
correspondence trustworthy enough to act on" -- and answers it from the cache,
so it costs nothing and can be run as often as it takes.

``--from``/``--to`` name *titles*; ``--source``/``--target`` name sites. The
directional pair is separate from the link layer's local/remote because a sync
is directional and a link is not.
"""


def get_direction(
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            envvar="WTBOT_LOCAL_LABEL",
            show_envvar=False,
            help="Registered site the work would be copied from.",
        ),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            envvar="WTBOT_REMOTE_LABEL",
            show_envvar=False,
            help="Registered site it would be copied to.",
        ),
    ] = None,
) -> dict[str, str | None]:
    """Dependency: the two sites, both optional, as the endpoint's fields."""
    return {"source_label": source, "target_label": target}


Direction = Depends(get_direction)

#: How each verdict prints, and whether it wants attention. Ordered the way a
#: reviewer reads the summary: work to do first, then trouble, then noise.
VERDICTS: dict[str, tuple[str, str | None]] = {
    "create": ("create", typer.colors.GREEN),
    "push": ("push", typer.colors.GREEN),
    "behind": ("behind", typer.colors.CYAN),
    "diverged": ("diverged", typer.colors.RED),
    "unlinked": ("unlinked", typer.colors.YELLOW),
    "source_missing": ("source only on target", typer.colors.CYAN),
    "unknown": ("unknown", typer.colors.YELLOW),
    "in_sync": ("in sync", None),
}


@app.command("report")
def report(
    index_title: str = typer.Option(
        ..., "--from", help="Index title on the source site, e.g. Index:Some book.djvu"
    ),
    target_index_title: str | None = typer.Option(
        None, "--to", help="Only needed when the two sides' index titles differ"
    ),
    show: str = typer.Option(
        "actionable", help="Filter the listing: all | actionable | problems"
    ),
    direction: dict = Direction,
    api: ApiClient = Depends(get_api),
) -> None:
    """What a sync from one site's copy of a work to the other's would do.

    Writes nothing, to either wiki or to the local model -- not even the
    pairings it reads. Tracking a work is a separate, deliberate act
    (`wtbot link track-work`).

    The target index need not exist: that is the case this is most useful for,
    and every page then reports `create`.
    """
    data = api.post(
        "/sync/report",
        {
            **direction,
            "index_title": index_title,
            "target_index_title": target_index_title,
        },
    )

    source, target = data["source"], data["target"]
    typer.echo(f"{source['site']}  ->  {target['site']}")
    for side in (source, target):
        state = "" if side["exists"] else "  (does not exist)"
        placeholders = (
            f", {side['placeholder_pages']} untranscribed"
            if side["placeholder_pages"]
            else ""
        )
        typer.echo(
            f"  {side['index_title']}{state}"
            f"  [{side['cached_pages']} page(s) cached{placeholders}]"
        )

    for asset in data["assets"]:
        held = (
            "both"
            if asset["source_cached"] and asset["target_cached"]
            else (
                "source only"
                if asset["source_cached"]
                else "target only" if asset["target_cached"] else "neither"
            )
        )
        typer.echo(f"  {asset['kind']:<6} {asset['verdict']:<10} held: {held}")
        typer.echo(f"         {asset['detail']}")

    scan = data["scan"]
    colour = {
        "ok": typer.colors.GREEN,
        "mismatch": typer.colors.RED,
        "unverifiable": typer.colors.YELLOW,
    }[scan["status"]]
    typer.secho(f"  scan: {scan['status']} -- {scan['detail']}", fg=colour)

    for blocker in data["blockers"]:
        typer.secho(f"  BLOCKED: {blocker}", fg=typer.colors.RED)
    for advisory in data.get("advisories", []):
        typer.secho(f"  note: {advisory}", fg=typer.colors.YELLOW)

    counts = data["counts"]
    typer.echo(
        "  " + ("  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no pages")
    )

    for page in data["pages"]:
        if show == "actionable" and not page["actionable"]:
            continue
        if show == "problems" and page["verdict"] in ("in_sync", "create", "push"):
            continue
        label, colour = VERDICTS.get(page["verdict"], (page["verdict"], None))
        number = page["page_number"]
        line = (
            f"  {str(number) if number is not None else '?':>4}  {label:<22}"
            f" {page['source_title'] or page['target_title']}"
        )
        if page["source_ahead_by"] or page["target_ahead_by"]:
            line += (
                f"  (source +{page['source_ahead_by']},"
                f" target +{page['target_ahead_by']})"
            )
        if page["detail"]:
            line += f"  [{page['detail']}]"
        # The anchor's revids look identical whether it was asserted or found,
        # so the line has to say which -- it decides whether the row is ready.
        if page["linkable"]:
            line += "  (linkable)"
        typer.secho(line, fg=colour)

    ready, actionable = data["ready"], data["actionable"]
    summary = f"  {actionable} page(s) a push would write"
    if ready != actionable:
        summary += (
            f", {ready} of them ready ({data['unasserted_anchors']} need linking first)"
        )
    typer.echo(summary + ". This is a report: nothing has been changed.")


@app.command("fetch-assets")
def fetch_assets(
    index_title: str = typer.Option(
        ..., "--from", help="Index title on the source site"
    ),
    target_index_title: str | None = typer.Option(
        None, "--to", help="Only needed when the two sides' index titles differ"
    ),
    direction: dict = Direction,
    api: ApiClient = Depends(get_api),
) -> None:
    """Queue the report's fetch plan: the work's Index and its backing File.

    What to run when the report says the scan check could not run, or that it
    cannot see the target's index. Neither is a verdict -- both mean nobody has
    asked the wiki yet -- and the file may live on the wiki or on a shared
    repository (Commons), which the fetch follows either way.

    Assets only: the pages are a separate, far larger fetch.
    """
    data = api.post(
        "/sync/fetch-assets",
        {
            **direction,
            "index_title": index_title,
            "target_index_title": target_index_title,
        },
    )
    if not data["queued"]:
        typer.echo("nothing to fetch: the report already holds both assets")
        return
    for item in data["queued"]:
        typer.echo(f"  queued {item['title']} on {item['label']}  ({item['reason']})")
    typer.echo(data["note"])
