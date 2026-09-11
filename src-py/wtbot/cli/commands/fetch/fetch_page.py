import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api, get_context, get_label

app = TyperDI(
    no_args_is_help=True,
    name="page",
    help="commands relating to fetch wiki page to local cache",
)


@app.callback(invoke_without_command=True)
def fetch_page(
    ctx: typer.Context = Depends(get_context),
    title: str = typer.Argument(..., help="e.g. Index:Some_book.djvu"),
    depth: int = typer.Option(
        1, help="expansion depth: 0=page only, 1=expand Index/File"
    ),
    revisions: int = typer.Option(
        1,
        min=1,
        help=(
            "Revisions to store, counting back from the head. More than 1 fills "
            "in history for `wtbot link propose`, which cannot find an anchor at "
            "the head when one side was imported from an older revision."
        ),
    ),
    drain: bool = typer.Option(
        False,
        "--drain",
        help="Also work the queue now, instead of leaving it for `wtbot drain`.",
    ),
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Queue a cache-fill for one title on a registered site.

    Enqueues only: fetching is throttled to stay inside the wiki's rate limit,
    so an Index worth of pages takes minutes and does not belong inside this
    call. ``wtbot drain`` (or ``--drain``) does the work; ``wtbot drain
    --status`` shows what is left.

    For Index: and File: titles, depth=1 (the default) expands the work: blob
    download plus a child request per page.
    """
    if ctx.invoked_subcommand is not None:
        return

    # inspect(api)

    result = api.post(
        "/fetch/",
        {"title": title, "label": label, "depth": depth, "revisions": revisions},
    )
    request = result["request"]
    typer.echo(f"queued request #{request['pk']}  {title}  on {label}")

    if not drain:
        typer.echo("  run `wtbot drain` to fetch it")
        return

    report = api.post("/fetch/drain")
    typer.echo(
        f"drained {report['handled']} request(s); {report['remaining']} remaining"
    )

    request = api.get(f"/fetch/{request['pk']}")
    typer.echo(
        f"request #{request['pk']}  status={request['status']}  "
        f"progress={request['progress_done']}/{request['progress_total']}"
    )
    if request.get("error_message"):
        typer.echo(f"  error = {request['error_message']}")
