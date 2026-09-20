import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=False,
    name="page-numbers",
)

"""Thin wrapper over `GET /locator-index/page-numbers` — see that endpoint's
docstring (`wtbot.api.locator_index.router`) for the resolution rules."""


@app.callback(invoke_without_command=True)
def page_numbers(
    path: str = typer.Option(
        ...,
        "--path",
        help="wikisource:// VFS path of the Index: or any Page: within it",
    ),
    query: str = typer.Argument(
        ..., help="the printed page number/label to match, e.g. '273'"
    ),
    min_confidence: str = typer.Option(
        "inferred",
        "--min-confidence",
        help="'explicit' only, or 'inferred' (default) to also count on from one",
    ),
    limit: int = typer.Option(20, min=1, max=200),
    api: ApiClient = Depends(get_api),
) -> None:
    """Find the `Page:` holding a printed page number."""
    matches = api.get(
        "/locator-index/page-numbers",
        path=path,
        query=query,
        min_confidence=min_confidence,
        limit=limit,
    )
    if not matches:
        typer.echo("no match")
        return
    for match in matches:
        page = match["page"]
        typer.echo(
            f"{match['label']:>6}  [{match['confidence']:<8}]  "
            f"scan {page['scan_page']:<4} {page['title']}"
        )
