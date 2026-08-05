import os

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=True,
    name="link",
    help="Cross-site correspondence between revisions (RemoteLink).",
)


def _base_url_option() -> str:
    return os.environ.get("WTBOT_API_URL", "http://127.0.100.1:8000")


BaseUrl = typer.Option(_base_url_option, help="wtbot API base URL")


def _post(base_url: str, path: str, payload: dict) -> dict:
    import httpx

    resp = httpx.post(f"{base_url.rstrip('/')}{path}", json=payload, timeout=300.0)
    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text)
        typer.secho(f"{resp.status_code}: {detail}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return resp.json()


@app.command("add")
def add(
    local_title: str = typer.Argument(..., help="Title on the local site"),
    remote_title: str | None = typer.Argument(
        None, help="Title on the remote site; defaults to the local title"
    ),
    local_family: str = typer.Option("mywikisource"),
    local_code: str = typer.Option("en"),
    remote_family: str = typer.Option("wikisource"),
    remote_code: str = typer.Option("en"),
    origin: str = typer.Option(
        "manual", help="copy | title_match | manual | reconciled"
    ),
    force: bool = typer.Option(
        False,
        help="Assert the link even when the heads hold different transcriptions.",
    ),
    base_url: str = BaseUrl,
) -> None:
    """Assert that one page on each site holds the same content.

    Links the two *head* revisions. Refuses a pair whose heads have diverged
    unless --force: a link states that two revisions are the same content, and
    asserting that of a diverged pair makes every later comparison lie.
    """
    data = _post(
        base_url,
        "/links/",
        {
            "local": {"family": local_family, "code": local_code},
            "remote": {"family": remote_family, "code": remote_code},
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
    local_family: str = typer.Option("mywikisource"),
    local_code: str = typer.Option("en"),
    remote_family: str = typer.Option("wikisource"),
    remote_code: str = typer.Option("en"),
    confirm: bool = typer.Option(
        False, help="Write links for every proposable pair (default: report only)."
    ),
    show: str = typer.Option(
        "all", help="Filter the listing: all | proposable | problems"
    ),
    base_url: str = BaseUrl,
) -> None:
    """Walk an index's pages and report what could be linked.

    Compares each pair's head revisions; pages pair on page number within the
    index, not on title text. Reports only unless --confirm, because a
    proposal is a guess from a comparison and a link outlives it.
    """
    data = _post(
        base_url,
        "/links/propose",
        {
            "local": {"family": local_family, "code": local_code},
            "remote": {"family": remote_family, "code": remote_code},
            "index_title": index_title,
            "remote_index_title": remote_index_title,
            "confirm": confirm,
        },
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

    if confirm:
        typer.echo(f"confirmed {data['confirmed']} link(s)")
    elif any(p["proposable"] for p in data["proposals"]):
        typer.echo("nothing written; re-run with --confirm to assert these")


@app.command("show")
def show(
    local_title: str = typer.Argument(..., help="Title on the local site"),
    remote_title: str | None = typer.Argument(
        None, help="Title on the remote site; defaults to the local title"
    ),
    local_family: str = typer.Option("mywikisource"),
    local_code: str = typer.Option("en"),
    remote_family: str = typer.Option("wikisource"),
    remote_code: str = typer.Option("en"),
    base_url: str = BaseUrl,
) -> None:
    """Show the ladder for a page pair, and whether its anchor is current."""
    import httpx

    params = {
        "local_family": local_family,
        "local_code": local_code,
        "local_title": local_title,
        "remote_family": remote_family,
        "remote_code": remote_code,
    }
    if remote_title:
        params["remote_title"] = remote_title
    resp = httpx.get(f"{base_url.rstrip('/')}/links/", params=params, timeout=60.0)
    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text)
        typer.secho(f"{resp.status_code}: {detail}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    data = resp.json()

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
