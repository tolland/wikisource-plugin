import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="vfs",
    help="Operate on the wikisource:// tree the plugin sees.",
)


@app.command("delete")
def delete(
    path: str = typer.Argument(
        ...,
        help="VFS path of the title, e.g. '/mywikisource/en/(Main)/Book/Foo'.",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Also delete subpages (and, for an Index, its Page: titles).",
    ),
    discard_local_edits: bool = typer.Option(
        False,
        "--discard-local-edits",
        help="Delete even titles with uncommitted local edits.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Actually delete. Without it, only show what deletion would remove.",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Remove a title from the local cache; the wiki is never touched.

    By default only the one node goes (as with a wiki page delete, its
    subpages stay); --recursive takes the subtree. Without --force this is the
    dry run: every check runs and the paths are listed, nothing is deleted.
    """
    result = api.delete(
        "/vfs/node",
        path=path,
        recursive=recursive,
        discard_local_edits=discard_local_edits,
        dry_run=not force,
    )

    verb = "would delete" if result["dry_run"] else "deleted"
    typer.echo(f"{verb} {len(result['deleted_paths'])} title(s):")
    for deleted in result["deleted_paths"]:
        typer.echo(f"  {deleted}")
    if result["dry_run"]:
        typer.secho("nothing deleted -- pass --force to delete these.", fg="yellow")
