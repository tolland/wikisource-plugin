import typer

# from mqttbot.callbacks import get_callback
# from mqttbot.commands import dump_config, run
#
# """Command-line interface for MQTT bot."""
#
#
# def create_app() -> typer.Typer:
#     callback = get_callback()
#     app = typer.Typer(
#         name="mqttbot",
#         help="MQTT-based Minecraft bot automation with Baritone integration",
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
