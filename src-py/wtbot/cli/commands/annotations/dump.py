import os
from pathlib import Path

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=False,
    name="dump",
)

"""Write the annotation tables to a portable JSON file — see
`wtbot.annotation_transfer` for what the file contains and why it is keyed
on (site label, page title) rather than on page pks."""


@app.callback(invoke_without_command=True)
def dump_cmd(
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="file to write; '-' writes the dump to stdout",
    ),
    label: str | None = typer.Option(
        None, "--label", help="limit the dump to one registered site"
    ),
    title: str | None = typer.Option(
        None, "--title", help="limit the dump to one page title"
    ),
    database_url: str | None = typer.Option(
        None, help="defaults to WTBOT_DATABASE_URL / sqlite:///database.db"
    ),
) -> None:
    """Dump scan annotations, text anchors and box→range links to a file.

    The dump carries each record's site label and page title alongside the
    page pk it came from, so it can be loaded back into a rebuilt database
    where the pks have all changed but the site labels and titles have not.
    """
    from sqlalchemy.exc import OperationalError

    from wtbot.annotation_transfer import dump_annotations
    from wtbot.db import create_db_engine

    url = database_url or os.environ.get("WTBOT_DATABASE_URL")
    engine = create_db_engine(url) if url else create_db_engine()
    # Deliberately no init_db: a dump is most useful taken *before* a
    # migration, and migrating the database one is trying to preserve is the
    # opposite of what was asked for.
    try:
        dump = dump_annotations(engine, site_label=label, title=title)
    except OperationalError as exc:
        typer.secho(
            f"{engine.url}: no wtbot tables here ({exc.orig})", fg="red", err=True
        )
        raise typer.Exit(1) from exc

    if str(output) == "-":
        typer.echo(dump.model_dump_json(indent=2))
        return

    dump.write(output)
    typer.echo(
        f"wrote {dump.record_count} record(s) across {len(dump.pages)} page(s) "
        f"to {output}"
    )
