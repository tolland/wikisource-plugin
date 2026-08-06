import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="site",
    help="Register and inspect the wikis wtbot may talk to.",
)

"""Site registration.

Registering a wiki is a deliberate step now. It used to happen as a side effect
of the first fetch that named a family/code, which meant a mistyped code
registered a second wiki, silently, with no credentials -- and then read from
it. Nothing about that was visible until a log line mentioned it.
"""


@app.command("add")
def add(
    label: str = typer.Option(
        ..., help="Unique name for this wiki; everything else addresses it by this."
    ),
    family: str = typer.Option(..., help="pywikibot family, e.g. 'wikisource'"),
    code: str = typer.Option(..., help="pywikibot language code, e.g. 'en'"),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help=(
            "Full action API endpoint. Required for anything not covered by a "
            "pywikibot family file -- a local or docker wiki, for instance."
        ),
    ),
    articlepath: str = typer.Option("/wiki/$1"),
    api: ApiClient = Depends(get_api),
) -> None:
    """Register a wiki."""
    site = api.post(
        "/sites/",
        {
            "label": label,
            "family": family,
            "code": code,
            "api_url": api_url,
            "articlepath": articlepath,
        },
    )
    typer.echo(
        f"registered {site['label']} ({site['family']}:{site['code']}) #{site['pk']}"
    )
    # Said once, at the point it can be acted on. Anonymous reads are not
    # second-class -- an unauthenticated client with a compliant User-Agent
    # gets the same 200 req/min as an ordinary account -- but writing back
    # needs an account, and that is what this wiki cannot do yet.
    typer.echo(
        f"  no credential yet: reads work anonymously, commits do not. "
        f"Add one with `wtbot site-credential add --label {label} ...`"
    )


@app.command("list")
def list_sites(api: ApiClient = Depends(get_api)) -> None:
    """The registered wikis, and whether each can write back."""
    sites = api.get("/sites/")
    if not sites:
        typer.echo("no sites registered -- add one with `wtbot site add`")
        return
    for site in sites:
        credential = api.get_optional(f"/sites/{site['pk']}/credential")
        who = credential["username"] if credential else "anonymous (read-only)"
        typer.echo(
            f"{site['label'] or '(unlabelled)':<24} "
            f"{site['family']}:{site['code']:<8} "
            f"{site['api_url'] or 'family file':<48} {who}"
        )


@app.command("show")
def show(
    label: str = typer.Argument(..., help="Site label"),
    api: ApiClient = Depends(get_api),
) -> None:
    """One wiki's registration, as stored."""
    site = api.get(f"/sites/by-label/{label}")
    for key in ("pk", "label", "family", "code", "api_url", "articlepath", "host"):
        typer.echo(f"{key:<16} {site.get(key)}")
    credential = api.get_optional(f"/sites/{site['pk']}/credential")
    typer.echo(
        f"{'credential':<16} "
        + (
            f"{credential['username']}"
            + (f"@{credential['bot_name']}" if credential.get("bot_name") else "")
            if credential
            else "none (reads only)"
        )
    )
