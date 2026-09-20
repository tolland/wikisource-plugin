import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=False,
    name="sections",
)

"""Thin wrapper over `GET /locator-index/sections` — see that endpoint's
docstring (`wtbot.api.locator_index.router`) for the resolution rules."""


@app.callback(invoke_without_command=True)
def sections(
    path: str = typer.Option(
        ...,
        "--path",
        help="wikisource:// VFS path of the Index: or any Page: within it",
    ),
    query: str = typer.Argument(
        ..., help="the section/paragraph id to match, e.g. '273' or '3.21'"
    ),
    roles: str = typer.Option(
        "begin,anchor_template",
        "--roles",
        help="comma-separated occurrence roles to search: begin, end, anchor_template",
    ),
    limit: int = typer.Option(20, min=1, max=200),
    api: ApiClient = Depends(get_api),
) -> None:
    """Find the `Page:` holding a `<section>`/`{{anchor}}` id."""
    matches = api.get(
        "/locator-index/sections", path=path, query=query, roles=roles, limit=limit
    )
    if not matches:
        typer.echo("no match")
        return
    for match in matches:
        page = match["page"]
        typer.echo(
            f"{match['section_id']:<10}  [{match['role']:<14}]  "
            f"scan {page['scan_page']:<4} {page['title']}"
        )
