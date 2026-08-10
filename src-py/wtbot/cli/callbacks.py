from typing import Annotated, Callable, Optional

import typer
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from wtbot import (
    __app_name__,
    __version__,
)
from wtbot.cli.deps import DEFAULT_BASE_URL, CliConfig


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{__app_name__} v{__version__}")
        raise typer.Exit()


def get_callback() -> Callable[..., None]:
    # noinspection PyUnusedLocal
    def callback(
        ctx: typer.Context,
        _: Annotated[
            Optional[bool],
            typer.Option(
                "--version",
                "-V",
                callback=_version_callback,
                is_eager=True,
            ),
        ] = None,
        verbose: Annotated[
            Optional[int],
            typer.Option(
                ...,
                "--verbose",
                "-v",
                envvar="WTBOT_VERBOSITY",
                count=True,
                help="increase verbosity",
                show_default=False,
                show_envvar=False,
                min=0,
                # max=1000,
                # callback=callback_verbose,
                # hidden=True,
            ),
        ] = None,
        base_url: Annotated[
            str,
            typer.Option(
                "--base-url",
                envvar="WTBOT_API_URL",
                show_envvar=False,
                help="wtbot API base URL",
            ),
        ] = DEFAULT_BASE_URL,
    ):
        ctx.obj = CliConfig(base_url=base_url)
        # inspect(ctx)
        if ctx.invoked_subcommand is None:
            typer.echo("No subcommand invoked")
            ctx.get_help()
            return

    return callback


def local_file_parser(local_file: str):
    print("in the local file parser")
    if local_file.startswith("file:///"):
        print("stripping prefix")
        return local_file.removeprefix("file://")
    elif local_file.startswith("https://"):
        data = get(local_file)
        import tempfile

        new_file, filename = tempfile.mkstemp()

        with open(new_file, "wb") as f:
            f.write(data.content)

        return filename

    return local_file


def get(url: str):
    """
    A wrapper around requests.get that retries on 5xx errors.
    :param url:
    :return:
    """
    retry_strategy = Retry(
        total=5,  # Here we configure the max retries
        backoff_factor=5,  # And here we are setting the backoff factor
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],  # These are the status codes we want to retry
        allowed_methods=[
            "GET",
            "POST",
            "PUT",
            "PATCH",
        ],  # These are the methods we want to retry
    )

    # We pass our Retry object in the max_retries kwarg
    adapter = HTTPAdapter(max_retries=retry_strategy)

    # First we create the Session object
    session = Session()

    # Then we mount the adapter for all http and https traffic
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session.get(url)
