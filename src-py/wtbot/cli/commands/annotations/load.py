import os
from pathlib import Path

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=False,
    name="load",
)

"""Read back a file written by `wtbot annotations dump`. Records are
re-attached by (site label, page title), so a dump survives a rebuilt cache
in which every page pk is different."""


@app.callback(invoke_without_command=True)
def load_cmd(
    input_file: Path = typer.Option(
        ...,
        "--input",
        "-i",
        help="dump file written by `wtbot annotations dump`",
    ),
    label: str | None = typer.Option(
        None,
        "--label",
        help="load every record against this site, whatever label it was "
        "dumped under",
    ),
    replace: bool = typer.Option(
        False, help="overwrite rows that already exist instead of keeping them"
    ),
    database_url: str | None = typer.Option(
        None, help="defaults to WTBOT_DATABASE_URL / sqlite:///database.db"
    ),
    dry_run: bool = typer.Option(
        False, help="report what would be loaded, write nothing"
    ),
) -> None:
    """Load annotations from a dump file into the database.

    Nothing is created implicitly: a record whose site or page is not in the
    target database is reported and skipped. Existing rows are kept unless
    --replace, so a load is safe to re-run.
    """
    from wtbot.annotation_transfer import AnnotationDump, load_annotations
    from wtbot.db import create_db_engine, init_db

    try:
        dump = AnnotationDump.read(input_file)
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(1) from exc

    url = database_url or os.environ.get("WTBOT_DATABASE_URL")
    engine = create_db_engine(url) if url else create_db_engine()
    init_db(engine)
    report = load_annotations(
        engine, dump, site_label=label, replace=replace, dry_run=dry_run
    )

    verb = "would load" if dry_run else "loaded"
    typer.echo(
        f"{verb} {report.written} record(s): {report.boxes} box(es), "
        f"{report.anchors} anchor(s), {report.links} link(s)"
    )
    if report.replaced:
        typer.echo(f"  ~ {report.replaced} existing row(s) overwritten")
    if report.skipped_existing:
        typer.echo(
            f"  = {report.skipped_existing} already in the database "
            "(pass --replace to overwrite)"
        )
    if report.missing_sites:
        typer.echo("no such site registered here:")
        for site_label in report.missing_sites:
            typer.echo(f"  ? {site_label}")
    if report.missing_pages:
        typer.echo(f"skipped {len(report.missing_pages)} page(s) not in this database:")
        for page in report.missing_pages:
            typer.echo(f"  ? {page}")
    for warning in report.warnings:
        typer.echo(f"  ! {warning}")
