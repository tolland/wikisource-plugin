from typing import Annotated

import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="link",
    help="Cross-site correspondence between revisions (RemoteLink).",
)

"""Driving RemoteLink from the command line.

Sites are named by ``--local``/``--remote``, which take the same registered
labels as ``--label`` elsewhere. Both, or neither: with neither, the server
matches the registered labels against its naming conventions
(``local``/``remote``, ``origin``/``upstream``, ``mywikisource``/
``wikisource``) so the common setup needs no flags at all. One label alone is
refused rather than paired with whatever else is registered -- silently
choosing the other side is one typo away from proposing links against the
wrong wiki.
"""


def get_pair(
    local: Annotated[
        str | None,
        typer.Option(
            "--local",
            envvar="WTBOT_LOCAL_LABEL",
            show_envvar=False,
            help="Registered site holding our copy (see `wtbot site list`).",
        ),
    ] = None,
    remote: Annotated[
        str | None,
        typer.Option(
            "--remote",
            envvar="WTBOT_REMOTE_LABEL",
            show_envvar=False,
            help="Registered site holding the other copy.",
        ),
    ] = None,
) -> dict[str, str | None]:
    """Dependency: the two site labels, both optional.

    Returned as the payload fragment the endpoints take, so no command has to
    remember the field names.
    """
    return {"local_label": local, "remote_label": remote}


Pair = Depends(get_pair)


@app.command("add")
def add(
    local_title: str = typer.Argument(..., help="Title on the local site"),
    remote_title: str | None = typer.Argument(
        None, help="Title on the remote site; defaults to the local title"
    ),
    origin: str = typer.Option(
        "manual", help="copy | title_match | manual | reconciled"
    ),
    force: bool = typer.Option(
        False,
        help="Assert the link even when the heads hold different transcriptions.",
    ),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """Assert that one page on each site holds the same content.

    Links the two *head* revisions. Refuses a pair whose heads have diverged
    unless --force: a link states that two revisions are the same content, and
    asserting that of a diverged pair makes every later comparison lie.
    """
    data = api.post(
        "/links/",
        {
            **pair,
            "local_title": local_title,
            "remote_title": remote_title,
            "origin": origin,
            "force": force,
        },
    )
    typer.echo(
        f"link #{data['pk']}  origin={data['origin']}  "
        f"revisions {data['local_revision_pk']} <-> {data['remote_revision_pk']}"
    )


@app.command("propose")
def propose(
    index_title: str = typer.Argument(..., help="e.g. Index:Some_book.djvu"),
    remote_index_title: str | None = typer.Option(
        None, "--to", help="Only needed when the two sides' index titles differ"
    ),
    confirm: bool = typer.Option(
        False, help="Write links for every proposable pair (default: report only)."
    ),
    show: str = typer.Option(
        "all", help="Filter the listing: all | proposable | problems"
    ),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """Walk an index's pages and report what could be linked.

    Compares each pair's head revisions; pages pair on page number within the
    index, not on title text. Reports only unless --confirm, because a
    proposal is a guess from a comparison and a link outlives it.
    """
    data = api.post(
        "/links/propose",
        {**pair, "index_title": index_title, "remote_index_title": remote_index_title},
    )

    counts = data["counts"]
    typer.echo(
        "  ".join(f"{outcome}={count}" for outcome, count in sorted(counts.items()))
        or "no pages found for that index"
    )

    for proposal in data["proposals"]:
        if show == "proposable" and not proposal["proposable"]:
            continue
        if show == "problems" and proposal["proposable"]:
            continue
        number = proposal["page_number"]
        marker = "+" if proposal["proposable"] else "-"
        line = (
            f" {marker} {str(number) if number is not None else '?':>4}  "
            f"{proposal['outcome']:<16} {proposal['local_title']}"
        )
        if proposal.get("significance"):
            line += f"  [{proposal['significance']}]"
        if proposal.get("detail"):
            line += f"  ({proposal['detail']})"
        typer.echo(line)

    if not confirm:
        if any(p["proposable"] for p in data["proposals"]):
            typer.echo("nothing written; re-run with --confirm to assert these")
        return

    # Confirmed as a second call over the same proposals rather than a flag on
    # the first: what gets written is then exactly what was just printed.
    written = api.post(
        "/links/propose",
        {
            **pair,
            "index_title": index_title,
            "remote_index_title": remote_index_title,
            "confirm": True,
        },
    )
    typer.echo(f"confirmed {written['confirmed']} link(s)")


@app.command("show")
def show(
    local_title: str = typer.Argument(..., help="Title on the local site"),
    remote_title: str | None = typer.Argument(
        None, help="Title on the remote site; defaults to the local title"
    ),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """Show the ladder for a page pair, and whether its anchor is current."""
    params = {k: v for k, v in pair.items() if v}
    params["local_title"] = local_title
    if remote_title:
        params["remote_title"] = remote_title

    data = api.get("/links/", **params)

    typer.echo(f"{data['local_title']}  <->  {data['remote_title']}")
    typer.echo(
        f"  heads: local revid {data['local_head_revid']}, "
        f"remote revid {data['remote_head_revid']}"
    )
    if not data["rungs"]:
        typer.echo("  no links: the pair has never been linked")
        return

    for rung in data["rungs"]:
        typer.echo(
            f"  #{rung['pk']:<5} {rung['origin']:<12} "
            f"{rung['local_revision_pk']} <-> {rung['remote_revision_pk']}"
        )
    if data["anchor_is_current"]:
        typer.echo("  anchor is current")
    else:
        # Not an error: the link stays true, and the distance from it is
        # exactly what says the pages have moved since it was asserted.
        typer.echo("  anchor is behind the heads (the pages moved since)")
