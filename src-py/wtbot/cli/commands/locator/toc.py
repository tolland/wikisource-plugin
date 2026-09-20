import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=False,
    name="toc",
)

"""Dumps an Index's resolved printed-page numbering, one line per scan page
-- the reverse direction of `wtbot dev extract-outline`, which reads a PDF's
own bookmarks/labels and writes a `<pagelist>`. Here the `<pagelist>` is the
input (already on the Index page) and this prints what it resolves to,
scan page by scan page, via `GET /locator-index/dump`.

Deliberately flat rather than grouped into bookmark-like sections: an Index's
`<pagelist>` carries page *numbering*, not chapter titles, so there is
nothing here to group by -- see the `pagelist_assignments`/`sections`
listings in `wtbot locator dump` for the pieces a future "write real PDF
bookmarks back" step would still need titles for.
"""


@app.callback(invoke_without_command=True)
def toc(
    path: str = typer.Option(
        ...,
        "--path",
        help="wikisource:// VFS path of the Index: or any Page: within it",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Print each scan page's resolved printed-page label."""
    data = api.get("/locator-index/dump", path=path)

    for entry in data["pages"]:
        page = entry["page"]
        label = entry["label"] if entry["label"] is not None else "-"
        typer.echo(f"{page['scan_page']:<5} {label:>6}  [{entry['confidence']}]")
