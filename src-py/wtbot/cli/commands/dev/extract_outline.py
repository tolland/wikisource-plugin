from pathlib import Path
from typing import Annotated

import typer
from typer_di import TyperDI

from wtbot.cli.callbacks import local_file_parser
from wtbot.cli.commands.pdf_outline_utils import PdfOutline

app = TyperDI(
    no_args_is_help=True,
    name="extract-outline",
    help="Generate pagelists from PDF bookmarks and labels.",
)


@app.command("extract-outline")
def extract_outline(
    pdf_filepath: Annotated[
        Path,
        typer.Option(
            exists=True,
            file_okay=True,
            dir_okay=False,
            # writable=False,
            readable=True,
            resolve_path=True,
            parser=local_file_parser,
        ),
    ],
    depth: Annotated[
        int,
        typer.Option(
            min=1,
            help=(
                "Deepest bookmark level that starts a section. Use 2 for books "
                "that group their chapters under a 'Part' bookmark."
            ),
        ),
    ] = 1,
) -> None:
    """Generate pagelists from PDF bookmarks and labels, or all scans as a fallback."""
    try:
        outline = PdfOutline(pdf_filepath, depth=depth)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--pdf-filepath") from exc

    for entry in outline.entries:
        typer.echo(f"{entry.title}\n{outline.pagelist(entry)}\n")
