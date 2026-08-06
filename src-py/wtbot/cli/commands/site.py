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
