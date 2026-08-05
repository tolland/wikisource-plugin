import typer
from typer_di import TyperDI

from wtbot.cli.utils import _settings

app = TyperDI(
    name="show-config",
)


@app.callback(invoke_without_command=True)
def show_config(
    ctx: typer.Context,
    family: str = typer.Option("wikisource"),
    code: str = typer.Option("en"),
    api_url: str | None = typer.Option(None),
    ca_bundle: str | None = typer.Option(None),
) -> None:
    """Print the resolved WikiSettings (no network)."""

    if ctx.invoked_subcommand is not None:
        return

    typer.echo(_settings(family, code, api_url, ca_bundle))
