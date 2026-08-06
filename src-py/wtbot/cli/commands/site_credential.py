import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api, get_label

app = TyperDI(
    no_args_is_help=True,
    name="site-credential",
    help="The account wtbot logs in as, per site.",
)

"""Per-site credentials.

What authentication buys, precisely, so it is asked for on real grounds:

- **Writing back.** A commit is an edit, and an edit needs an account.
- **A higher read ceiling, eventually.** Wikimedia grants an *established*
  editor 2,000 req/min against 200 for everyone else -- but "established" is
  not something an account can be given on request, and no API reports which
  tier a request landed in.

What it does not buy is a better read rate today: an unauthenticated client
with a policy-compliant User-Agent gets the same 200 req/min as a new account.
Reading a public wiki anonymously is a legitimate configuration, not a
misconfiguration, which is why nothing here refuses to fetch without it.
<https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits>

The password is stored in plaintext in the local SQLite file, as it is for any
single-user dev tool of this shape. Prefer a BotPassword
(``--bot-password-suffix``) over an account password: it is revocable on its
own and can be scoped to the rights a bot needs.
"""


@app.command("add")
def add(
    username: str = typer.Option(..., help="Wiki account name, without any @suffix."),
    password: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        help="Account password, or the BotPassword secret when a suffix is given.",
    ),
    bot_password_suffix: str | None = typer.Option(
        None,
        "--bot-password-suffix",
        help=(
            "The name half of a BotPassword ('wtbot' in 'Admin@wtbot'). "
            "Preferred: separately revocable and separately scoped."
        ),
    ),
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Set (or replace) the account for a site. Upserts: one per site."""
    site = api.get(f"/sites/by-label/{label}")
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
    typer.echo(f"{label} will log in as {who}")


@app.command("show")
def show(
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Who a site logs in as. Never prints the password."""
    site = api.get(f"/sites/by-label/{label}")
    credential = api.get_optional(f"/sites/{site['pk']}/credential")
    if credential is None:
        typer.echo(f"{label}: no credential -- reads work, commits do not")
        return
    who = credential["username"]
    if credential.get("bot_name"):
        who = f"{who}@{credential['bot_name']}"
    typer.echo(f"{label}: {who} (updated {credential['updated_at']})")


@app.command("remove")
def remove(
    label: str = Depends(get_label),
    api: ApiClient = Depends(get_api),
) -> None:
    """Forget a site's account. The site itself stays registered."""
    site = api.get(f"/sites/by-label/{label}")
    api.delete(f"/sites/{site['pk']}/credential")
    typer.echo(f"{label}: credential removed; it will read anonymously")
