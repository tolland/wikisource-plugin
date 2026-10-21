from pathlib import Path
from typing import Annotated

import typer
import yaml
from typer_di import TyperDI

from wtbot.cli.callbacks import local_file_parser
from wtbot.cli.commands.pdf_outline_utils import PdfOutline
from wtbot.structure_pagelist import structure_pagelists
from wtbot.work_outline import load_proposal

app = TyperDI(
    no_args_is_help=True,
    name="extract-outline",
    help="Generate pagelists from PDF bookmarks or transclusion YAML.",
)


@app.command("extract-outline")
def extract_outline(
    pdf_filepath: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            file_okay=True,
            dir_okay=False,
            # writable=False,
            readable=True,
            resolve_path=True,
            parser=local_file_parser,
        ),
    ] = None,
    structure: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Edited transclusion YAML; no PDF is needed.",
        ),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option(
            min=1,
            help=(
                "Deepest level that starts a section. Defaults to 1 for PDF bookmarks "
                "and 99 for an edited structure."
            ),
        ),
    ] = None,
) -> None:
    """Generate pagelists from a PDF or an edited transclusion structure."""
    if (pdf_filepath is None) == (structure is None):
        raise typer.BadParameter("Supply exactly one of --pdf-filepath or --structure")
    if structure is not None:
        try:
            output = structure_pagelists(load_proposal(structure), depth=depth or 99)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--structure") from exc
        typer.echo(output, nl=False)
        return
    try:
        outline = PdfOutline(pdf_filepath, depth=depth or 1)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--pdf-filepath") from exc

    for entry in outline.entries:
        typer.echo(f"{entry.title}\n{outline.pagelist(entry)}\n")
