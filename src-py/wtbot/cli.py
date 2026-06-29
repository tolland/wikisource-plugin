import typer

# from wtbot.callbacks import get_callback
# from wtbot.commands import dump_config, run
#
# """Command-line interface for wiki filesystem service."""
#
#
# def create_app() -> typer.Typer:
#     callback = get_callback()
#     app = typer.Typer(
#         sitename="wtbot",
#         help="python service to implement the backing for a mediawiki wiki filesystem",
#         add_completion=False,
#         pretty_exceptions_enable=False,
#     )
#     app.callback()(callback)
#     app.add_typer(run.app)
#     app.add_typer(dump_config.app)
#     return app


def run_cli() -> None:
    """Entry point for the CLI."""
    # app = create_app()
    # app()


if __name__ == "__main__":
    run_cli()
