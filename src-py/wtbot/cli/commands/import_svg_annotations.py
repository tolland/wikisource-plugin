import os

import typer
from typer_di import TyperDI

"""
This is a convenience command to import an earlier serialization of the
annoation bounding box into the current format.
@TODO probably should remove this if its not being used
"""

app = TyperDI(
    no_args_is_help=True,
    name="import-svg-annotations",
)


@app.callback(invoke_without_command=True)
def import_svg_annotations_cmd(
    blob_root: str = typer.Option(
        lambda: os.environ.get("WTBOT_BLOB_ROOT", "./blobs"),
        help="blob root containing the legacy annotations/*.svg documents",
    ),
    database_url: str | None = typer.Option(
        None, help="defaults to WTBOT_DATABASE_URL / sqlite:///database.db"
    ),
    dry_run: bool = typer.Option(
        False, help="report what would be imported, write nothing"
    ),
) -> None:
    """One-shot import of legacy per-page SVG annotation documents into the
    ScanAnnotation table.

    Reads blob_root/annotations/{page_pk}.svg (the pre-SQL storage), inserts
    every identifiable <rect> as a ScanAnnotation row, and reports anything
    it could not carry over (non-rect shapes, unsupported transforms). Rows
    that already exist are left alone, so re-running is safe. The SVG files
    are not deleted — remove the directory yourself once satisfied.
    """
    from pathlib import Path

    from wtbot.annotation_svg_import import import_svg_annotations
    from wtbot.db import create_db_engine, init_db

    url = database_url or os.environ.get("WTBOT_DATABASE_URL")
    engine = create_db_engine(url) if url else create_db_engine()
    init_db(engine)
    report = import_svg_annotations(engine, Path(blob_root), dry_run=dry_run)

    verb = "would import" if dry_run else "imported"
    typer.echo(f"{verb} {len(report.imported)} annotation(s)")
    for key in report.imported:
        typer.echo(f"  + {key}")
    if report.skipped_existing:
        typer.echo(f"skipped {len(report.skipped_existing)} already in the database:")
        for key in report.skipped_existing:
            typer.echo(f"  = {key}")
    if report.skipped_pages:
        typer.echo("skipped files with no matching Page row:")
        for name in report.skipped_pages:
            typer.echo(f"  ? {name}")
    for warning in report.warnings:
        typer.echo(f"  ! {warning}")
