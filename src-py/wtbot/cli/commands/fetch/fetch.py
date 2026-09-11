from typer_di import TyperDI

from wtbot.cli.commands.fetch import drain, fetch_page, fetch_refresh

app = TyperDI(
    no_args_is_help=True,
    name="fetch",
    help="commands relating to fetch wiki page to local cache",
)

app.add_typer(drain.app, rich_help_panel="Fetch Page")
app.add_typer(fetch_page.app, rich_help_panel="Fetch Page")
app.add_typer(fetch_refresh.app, rich_help_panel="Fetch Page")
