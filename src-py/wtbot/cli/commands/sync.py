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

``batches``/``batch``/``approve``/``push`` are the CLI side of the push queue
that ``/sync/batches`` and ``/sync-page`` stage (viewer routes, or
``POST /sync/batches`` / ``POST /sync/page-batches`` directly): watching an
approved run and pushing it one page at a time without a browser open. They
are thin wrappers over that same HTTP contract -- there is no separate CLI-only
path to a wiki -- so a batch staged from the viewer can be approved there and
pushed from here, or the reverse.
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


# --- the push queue: batches, approval, and pushing one page at a time -----


_ROW_COLOUR: dict[str, str | None] = {
    "pushed": typer.colors.GREEN,
    "conflict": typer.colors.YELLOW,
    "error": typer.colors.RED,
    "staged": None,
    "skipped": None,
}


def _print_row(row: dict) -> None:
    line = f"    #{row['pk']:<4} {row['status']:<9} {row['target_title']}"
    if row["result_revid"]:
        line += f"  -> revid {row['result_revid']}"
    typer.secho(line, fg=_ROW_COLOUR.get(row["status"]))
    if row.get("error_message"):
        typer.secho(
            f"           {row['error_message']}", fg=_ROW_COLOUR.get(row["status"])
        )


def _print_batch(batch: dict) -> None:
    typer.echo(
        f"#{batch['pk']}  {batch['status']}  "
        f"{batch['source_site']} -> {batch['target_site']}"
        + (f"  ({batch['label']})" if batch["label"] else "")
    )
    if batch["approved_by"]:
        typer.echo(f"  approved by {batch['approved_by']}")
    for row in batch["promotions"]:
        _print_row(row)
    typer.echo(f"  {batch['remaining']} still staged")


def _diff_pushed(before: list[dict], after: list[dict]) -> dict | None:
    """Which row a push call just settled.

    The push endpoint returns the whole batch, not the row it acted on -- so
    the row is found by comparing two snapshots for the one that stopped
    being ``staged``, rather than trusting a promotion pk this caller may not
    have (the common case is "push the next one", whichever that is).
    """
    was_staged = {row["pk"] for row in before if row["status"] == "staged"}
    for row in after:
        if row["pk"] in was_staged and row["status"] != "staged":
            return row
    return None


@app.command("batches")
def list_batches(api: ApiClient = Depends(get_api)) -> None:
    """List every staged push run, newest first -- work-level or single-page.

    What is pending, and whether any promotion came back with an error,
    without opening a batch to look.
    """
    batches = api.get("/sync/batches")
    if not batches:
        typer.echo("no runs staged yet")
        return
    for batch in batches:
        counts = batch["counts"]
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"
        typer.echo(
            f"  #{batch['pk']:<4} {batch['status']:<9} "
            f"{batch['source_site']} -> {batch['target_site']}  "
            f"{batch['label'] or batch['source_index_title']}  [{summary}]"
        )


@app.command("batch")
def show_batch(
    batch_pk: int = typer.Argument(..., help="The batch to show."),
    api: ApiClient = Depends(get_api),
) -> None:
    """Show one batch's promotions and their current status.

    The CLI counterpart of the viewer's `/sync/batches/<pk>` screen: what is
    still staged, what pushed, and the error message on anything that did not.
    """
    _print_batch(api.get(f"/sync/batches/{batch_pk}"))


@app.command("approve")
def approve_batch(
    batch_pk: int = typer.Argument(..., help="The batch to approve."),
    approved_by: str = typer.Option(..., "--by", help="Who is signing this off."),
    api: ApiClient = Depends(get_api),
) -> None:
    """Sign a draft batch off. Nothing pushes until this has run."""
    _print_batch(
        api.post(f"/sync/batches/{batch_pk}/approve", {"approved_by": approved_by})
    )


@app.command("push")
def push_batch(
    batch_pk: int = typer.Argument(..., help="The batch to push from."),
    promotion_pk: int | None = typer.Option(
        None,
        "--promotion",
        help="Push this row specifically. Omit for the next staged one.",
    ),
    all_rows: bool = typer.Option(
        False,
        "--all",
        help=(
            "Walk every staged row, one request at a time, stopping the "
            "moment one does not push cleanly."
        ),
    ),
    force: bool = typer.Option(
        False,
        help=(
            "Write even when the source moved since staging, or the "
            "target's base revid no longer matches."
        ),
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Push one page of an approved batch -- or, with --all, the rest of it.

    One HTTP request per page throughout, the same discipline the viewer's
    "push the next page" button keeps: a rate-limited wiki gets one request
    rather than the whole batch, and a run can be watched, paused and picked
    up again between calls -- ``wtbot sync batch <pk>`` shows where it stands
    without pushing anything further. A batch staged from ``sync-page`` has
    exactly one row, so a bare ``wtbot sync push <pk>`` is the whole thing.
    """
    if promotion_pk is not None and all_rows:
        typer.secho("--promotion and --all are mutually exclusive", fg="red", err=True)
        raise typer.Exit(2)

    pushed = 0
    batch = api.get(f"/sync/batches/{batch_pk}")
    while True:
        if batch["remaining"] == 0:
            if pushed == 0:
                typer.echo(f"batch {batch_pk} has no staged rows left")
            break

        before_rows = batch["promotions"]
        payload: dict = {"force": force}
        if promotion_pk is not None:
            payload["promotion_pk"] = promotion_pk
        batch = api.post(f"/sync/batches/{batch_pk}/push", payload)
        pushed += 1

        row = _diff_pushed(before_rows, batch["promotions"])
        if row is not None:
            _print_row(row)

        if not all_rows:
            break
        if row is not None and row["status"] in ("conflict", "error"):
            typer.secho(
                f"stopped after {pushed} page(s): a row did not push cleanly",
                fg=typer.colors.YELLOW,
            )
            break

    if pushed:
        typer.echo(
            f"batch {batch_pk}: {batch['status']}, {batch['remaining']} still staged"
        )


@app.command("abort")
def abort_batch(
    batch_pk: int = typer.Argument(..., help="The batch to abort."),
    api: ApiClient = Depends(get_api),
) -> None:
    """Stop a run. Staged rows are skipped; pushed rows stay pushed.

    No undo: reversing a push means appending another revision, which is a
    separate, deliberate act.
    """
    _print_batch(api.post(f"/sync/batches/{batch_pk}/abort"))
