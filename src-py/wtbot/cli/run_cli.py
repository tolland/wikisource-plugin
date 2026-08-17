import typer

from wtbot.cli.callbacks import get_callback
from wtbot.cli.commands import (
    dev,
    drain,
    fetch_page,
    fetch_refresh,
    import_svg_annotations,
    link,
    page,
    show_config,
    site,
    site_credential,
    sync,
)

"""Typer CLI for wtbot. Thin demonstration of the wiki-access seam from the
command line; the same WikiSettings injection works under tests and IntelliJ."""


def create_app() -> typer.Typer:

    callback = get_callback()

    cli = typer.Typer(
        help="wtbot — Wikisource editor backend",
        add_completion=False,
        no_args_is_help=True,
        pretty_exceptions_enable=False,
        pretty_exceptions_short=False,
        # rich_markup_mode=None,
        # @TODO according to doc, this should work. but does not
        # <https://typer.tiangolo.com/tutorial/commands/callback/#adding-a-callback-on-creation>
        # callback=callback,
    )

    cli.callback()(callback)

    cli.add_typer(site.app, rich_help_panel="Model commands")
    cli.add_typer(site_credential.app, rich_help_panel="Model commands")
    cli.add_typer(link.app, rich_help_panel="Model commands")
    cli.add_typer(page.app, rich_help_panel="Model commands")
    cli.add_typer(dev.app, rich_help_panel="Development")
    cli.add_typer(drain.app)
    cli.add_typer(fetch_page.app)
    cli.add_typer(fetch_refresh.app)
    cli.add_typer(sync.app)
    cli.add_typer(show_config.app, rich_help_panel="Tools")
    cli.add_typer(import_svg_annotations.app, rich_help_panel="Tools")

    return cli


def run_cli() -> None:
    app = create_app()

    # debug inspection stuff goes here. e.g. start a pydevd and attach it

    app()


if __name__ == "__main__":
    run_cli()
