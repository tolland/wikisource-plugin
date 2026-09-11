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

Credentials belong to that same step, which is why ``add`` takes them: a
registered wiki that cannot log in cannot be fetched from (wtbot authenticates
by default) and cannot be committed to at all, so leaving it for later leaves
the wiki unusable in a way that only shows up on the next command.
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
    read_throttle: float | None = typer.Option(
        None,
        "--read-throttle",
        min=0,
        help=(
            "Minimum seconds between API reads for this site. Defaults to the "
            "process policy (0.35s); local Docker wikis can use e.g. 0.01."
        ),
    ),
    username: str | None = typer.Option(
        None, help="Wiki account to log in as. Without it the site cannot be used."
    ),
    password: str | None = typer.Option(
        None,
        help="Account password, or the BotPassword secret with --bot-password-suffix.",
    ),
    bot_password_suffix: str | None = typer.Option(
        None,
        "--bot-password-suffix",
        help="The name half of a BotPassword ('wtbot' in 'Admin@wtbot').",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Register a wiki, with the account wtbot should log in as."""
    if username and not password:
        password = typer.prompt("password", hide_input=True)
    site = api.post(
        "/sites/",
        {
            "label": label,
            "family": family,
            "code": code,
            "api_url": api_url,
            "articlepath": articlepath,
            "read_throttle": read_throttle,
        },
    )
    typer.echo(
        f"registered {site['label']} ({site['family']}:{site['code']}) #{site['pk']}"
    )

    if username:
        credential = api.put(
            f"/sites/{site['pk']}/credential",
            {
                "username": username,
                "password": password,
                "bot_name": bot_password_suffix,
            },
        )
        who = credential["username"]
        if credential.get("bot_name"):
            who = f"{who}@{credential['bot_name']}"
        typer.echo(f"  logs in as {who}")
        return

    # Said at the point it can be acted on, and stated as the blocker it is:
    # fetching refuses an uncredentialed site, so this wiki is registered but
    # unusable until an account is added.
    typer.secho(
        f"  no credential: fetches from {label} will be refused, and commits "
        f"are impossible without one.",
        fg="yellow",
    )
    typer.echo(
        f"  add one with `wtbot site-credential add --label {label} "
        f"--username ...`, or set WTBOT_ALLOW_ANONYMOUS=1 to read without it"
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
            f"{site['api_url'] or 'family file':<48} {who} "
            "read-throttle="
            f"{site.get('read_throttle') if site.get('read_throttle') is not None else 'default'}"
        )


@app.command("show")
def show(
    label: str = typer.Argument(..., help="Site label"),
    api: ApiClient = Depends(get_api),
) -> None:
    """One wiki's registration, as stored."""
    site = api.get(f"/sites/by-label/{label}")
    for key in (
        "pk",
        "label",
        "family",
        "code",
        "api_url",
        "articlepath",
        "read_throttle",
    ):
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


@app.command("update")
def update(
    label: str = typer.Argument(..., help="Site label"),
    read_throttle: float = typer.Option(
        ...,
        "--read-throttle",
        min=0,
        help="Minimum seconds between reads; use 0 to disable pacing.",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Update the per-site request pacing without re-registering the wiki."""
    site = api.get(f"/sites/by-label/{label}")
    updated = api.put(
        f"/sites/{site['pk']}",
        {
            "label": site["label"],
            "family": site["family"],
            "code": site["code"],
            "api_url": site.get("api_url"),
            "articlepath": site.get("articlepath") or "/wiki/$1",
            "read_throttle": read_throttle,
        },
    )
    typer.echo(f"updated {updated['label']}: read throttle {updated['read_throttle']}s")


@app.command("delete")
def delete(
    label: str = typer.Argument(..., help="Site label"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Actually delete. Without it, only show what deletion would remove.",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Delete a wiki and its whole local cache -- pages, revisions, queue, all.

    There is no separate dry run: without --force this *is* the dry run,
    printing the rows that would go and touching nothing.
    """
    site = api.get(f"/sites/by-label/{label}")
    plan = (
        api.delete(f"/sites/{site['pk']}")
        if force
        else api.get(f"/sites/{site['pk']}/delete-plan")
    )

    verb = "deleted" if force else "would delete"
    typer.echo(f"{verb} from {plan['label']} ({plan['family']}:{plan['code']}):")
    for entry in plan["counts"]:
        typer.echo(f"  {entry['table']:<20} {entry['rows']:>8}")
    if not force:
        typer.secho(
            f"nothing deleted -- run `wtbot site delete {label} --force` to "
            f"delete these rows.",
            fg="yellow",
        )
