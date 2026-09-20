import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=False,
    name="dump",
)

"""Thin wrapper over `GET /locator-index/dump` — see that endpoint's
docstring (`wtbot.api.locator_index.router`) for what it returns and why it
is unfiltered rather than a targeted lookup."""


@app.callback(invoke_without_command=True)
def dump(
    path: str = typer.Option(
        ...,
        "--path",
        help="wikisource:// VFS path of the Index: or any Page: within it",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Dump everything the locator index knows about one work."""
    data = api.get("/locator-index/dump", path=path)

    typer.echo(f"{data['index_title']}  ({data['index_path']})")

    typer.echo(f"\npagelist assignments ({len(data['pagelist_assignments'])}):")
    for entry in data["pagelist_assignments"]:
        detail = entry["text"] or entry["value"]
        style = f" [{entry['style']}]" if entry["style"] else ""
        typer.echo(f"  scan {entry['scan_page']:<4} {entry['kind']:<7} {detail}{style}")

    typer.echo(f"\npages ({len(data['pages'])}):")
    for entry in data["pages"]:
        page = entry["page"]
        label = entry["label"] if entry["label"] is not None else "-"
        typer.echo(
            f"  scan {page['scan_page']:<4} {label:>6}  "
            f"[{entry['confidence']:<8}]  {page['title']}"
        )

    typer.echo(f"\nsections ({len(data['sections'])}):")
    for match in data["sections"]:
        page = match["page"]
        typer.echo(
            f"  {match['section_id']:<10}  [{match['role']:<14}]  "
            f"scan {page['scan_page']:<4} {page['title']}"
        )
