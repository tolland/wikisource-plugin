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

    Links the newest revision pair that actually matches -- which is not always
    the two heads: a page imported from an older revision of the other side
    anchors there, and the edits since are what the anchor is the base for.

    Refuses a pair with no matching revision unless --force: a link states that
    two revisions are the same content, and asserting that of a diverged pair
    makes every later comparison lie.
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

    For each pair, finds the newest revision pair holding the same content and
    reports how far each side has moved since -- `local +1` means we have an
    edit the other side does not. Pages pair on page number within the index,
    not on title text.

    Reports only unless --confirm, because a proposal is a guess from a
    comparison and a link outlives it.
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
        # The distance from the anchor is the actionable part: it is what would
        # replay, and in which direction.
        ahead = []
        if proposal.get("local_ahead_by"):
            ahead.append(f"local +{proposal['local_ahead_by']}")
        if proposal.get("remote_ahead_by"):
            ahead.append(f"remote +{proposal['remote_ahead_by']}")
        if ahead:
            line += "  (" + ", ".join(ahead) + ")"
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


@app.command("pair-index")
def pair_index(
    index_title: str = typer.Argument(..., help="e.g. Index:Some_book.djvu"),
    remote_index_title: str | None = typer.Option(
        None, "--to", help="Only needed when the two sides' index titles differ"
    ),
    strict: bool = typer.Option(
        True,
        help=(
            "Refuse the work if any page has no counterpart. A work that does "
            "not line up is usually a wrong --to or a different scan."
        ),
    ),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """Pair a whole work's pages, before comparing any content.

    The step that makes a work navigable: a diverged page is only listable once
    its pair exists, so pairing comes first and content comparison second.
    """
    data = api.post(
        "/links/pairs/index",
        {
            **pair,
            "index_title": index_title,
            "remote_index_title": remote_index_title,
            "strict": strict,
        },
    )
    typer.echo(f"paired {data['paired']} page(s); {data['created']} new")
    for title in data["unpaired"]:
        typer.secho(f"  no counterpart: {title}", fg=typer.colors.YELLOW)


@app.command("pairs")
def pairs(
    index_title: str | None = typer.Option(None, "--index", help="Narrow to one work"),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """List page pairings and how much is linked under each."""
    params = {k: v for k, v in pair.items() if v}
    if index_title:
        params["index_title"] = index_title
    data = api.get("/links/pairs", **params)

    if not data["pairs"]:
        typer.echo("no pairings")
        return
    for row in data["pairs"]:
        number = row["page_number"]
        state = "anchored" if row["anchor_is_current"] else f"{row['rungs']} rung(s)"
        typer.echo(
            f"  #{row['pk']:<5} {str(number) if number is not None else '?':>4}  "
            f"{state:<14} {row['local_title']}"
        )


@app.command("works")
def works(
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """List tracked works -- the Index-to-Index correspondences.

    The unit above pairs: for Wikisource an Index is to a work what a
    repository is to its files, and "which works do we track" is the question
    asked before any page is looked at.
    """
    params = {k: v for k, v in pair.items() if v}
    data = api.get("/links/works", **params)

    if not data["works"]:
        typer.echo("no tracked works (`wtbot link track-work Index:...`)")
        return
    for row in data["works"]:
        unpaired = row["local_pages"] - row["pairs"]
        typer.echo(
            f"  #{row['pk']:<4} {row['local_site']} <-> {row['remote_site']}  "
            f"{row['linked']}/{row['pairs']} linked"
            + (f", {unpaired} unpaired" if unpaired > 0 else "")
        )
        typer.echo(f"        {row['local_title']}")
        if row["remote_title"] != row["local_title"]:
            typer.echo(f"        {row['remote_title']}")


@app.command("track-work")
def track_work(
    index_title: str = typer.Argument(..., help="Index title on the local site"),
    remote_index_title: str | None = typer.Option(
        None, "--to", help="Only needed when the two sides' index titles differ"
    ),
    pair_pages: bool = typer.Option(
        True, help="Also pair the work's Page: children, by page number."
    ),
    pair: dict = Pair,
    api: ApiClient = Depends(get_api),
) -> None:
    """Track a work: pair two Index: pages, and their pages with them.

    Idempotent -- re-running adopts page pairs made since, so "track, fetch
    more, track again" behaves the way it reads.
    """
    data = api.post(
        "/links/works",
        {
            **pair,
            "index_title": index_title,
            "remote_index_title": remote_index_title,
            "pair_pages": pair_pages,
        },
    )
    work = data["work"]
    state = "tracking" if data["created"] else "already tracked"
    typer.echo(
        f"{state} work #{work['pk']}: {work['pairs']} page pair(s) "
        f"({data['paired']} new, {data['adopted']} adopted)"
    )
    for title in data["unpaired"]:
        typer.secho(f"  no counterpart: {title}", fg=typer.colors.YELLOW)


@app.command("revisions")
def revisions(
    pair_pk: int = typer.Argument(..., help="Pairing pk (see `wtbot link pairs`)"),
    link_match: bool = typer.Option(
        False,
        "--link-best",
        help="Assert the closest unlinked match, rather than only reporting.",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Both sides' stored revisions, and every same-content pair among them.

    What to run on a page the proposer will not touch. `quality_differs` and
    `history_exhausted` both mean the anchor search found nothing *reachable
    from a head* -- it compares one side's head against the other's history and
    stops there. A page where both sides have edited since they last agreed has
    its matching pair sitting one or two revisions back on each side, and this
    is where it shows up.
    """
    data = api.get(f"/links/pairs/{pair_pk}/revisions")

    typer.echo(f"{data['local_title']}  <->  {data['remote_title']}")
    for side, rows, complete in (
        (data["local_site"], data["local"], data["local_history_complete"]),
        (data["remote_site"], data["remote"], data["remote_history_complete"]),
    ):
        typer.echo(f"  {side}" + ("" if complete else "  (history incomplete)"))
        for row in rows:
            marks = " ".join(
                filter(
                    None,
                    [
                        "head" if row["is_head"] else "",
                        "linked" if row["linked_to"] else "",
                    ],
                )
            )
            level = "" if row["level"] is None else f"level {row['level']}"
            typer.echo(
                f"    {row['revid']:<10} {level:<8} {row['user'] or '':<18}"
                f" {(row['comparable_sha1'] or '')[:10]}  {marks}"
            )

    if not data["matches"]:
        typer.secho("  no revision pair holds the same content", fg=typer.colors.YELLOW)
        if data["local_history_complete"] and data["remote_history_complete"]:
            # Worth saying plainly: this is the one case fetching cannot fix.
            typer.echo(
                "  both histories are complete, so these pages were written "
                "independently -- reconciling them is an edit, not a link"
            )
        return

    typer.echo("  same content:")
    for match in data["matches"]:
        state = f"linked #{match['link_pk']}" if match["linked"] else "not linked"
        typer.echo(
            f"    {match['local_revid']} <-> {match['remote_revid']}  "
            f"(local +{match['local_ahead_by']}, remote +{match['remote_ahead_by']})"
            f"  {state}"
        )

    if not link_match:
        if any(not m["linked"] for m in data["matches"]):
            typer.echo("nothing written; re-run with --link-best to assert the closest")
        return

    best = next((m for m in data["matches"] if not m["linked"]), None)
    if best is None:
        typer.echo("every match is already linked")
        return
    written = api.post(
        f"/links/pairs/{pair_pk}/rungs",
        {
            "local_revid": best["local_revid"],
            "remote_revid": best["remote_revid"],
            "origin": "manual",
        },
    )
    typer.echo(
        f"link #{written['pk']}  {best['local_revid']} <-> {best['remote_revid']}"
    )


@app.command("unpair")
def unpair_command(
    pair_pk: int = typer.Argument(..., help="Pairing pk (see `wtbot link pairs`)"),
    api: ApiClient = Depends(get_api),
) -> None:
    """Retract a pairing, and the revision links asserted under it.

    The wide retraction: use `unpair-revision` to drop the links and keep the
    pairing, which is what is usually wanted after a bad `propose`.
    """
    data = api.delete(f"/links/pairs/{pair_pk}")
    typer.echo(f"removed pairing {data['deleted']} and {data['rungs_removed']} rung(s)")


@app.command("unpair-revision")
def unpair_revision(
    link_pk: int | None = typer.Argument(
        None, help="Rung pk to retract (see `wtbot link show`)"
    ),
    pair_pk: int | None = typer.Option(
        None,
        "--pair",
        help="Retract every rung under this pairing (see `wtbot link pairs`).",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Retract a paired revision, keeping the page pairing.

    A rung says two *revisions* hold the same content. Retracting one says that
    was wrong -- a `propose` run against the wrong `--to`, or one confirmed
    before enough history had been fetched -- and says nothing about whether
    the two pages are the same page. `unpair` would answer that second question
    too, discarding the pairing and everything listed under it, and leaving the
    work to be paired from scratch before it can be proposed again.

    Takes a rung pk, or `--pair` to clear a whole ladder at once.
    """
    if (link_pk is None) == (pair_pk is None):
        typer.secho(
            "give a rung pk, or --pair to retract a whole ladder -- not both",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    if pair_pk is not None:
        data = api.delete(f"/links/pairs/{pair_pk}/rungs")
        typer.echo(
            f"retracted {data['rungs_removed']} rung(s); "
            f"pairing {data['pairing']} kept"
        )
        return

    data = api.delete(f"/links/{link_pk}")
    # `pairing` is None only for a rung written before pairings were stored --
    # there is then nothing to reassure the caller about.
    kept = f"pairing {data['pairing']} kept" if data.get("pairing") else "pairing kept"
    typer.echo(f"retracted rung {data['deleted']}; {kept}")
