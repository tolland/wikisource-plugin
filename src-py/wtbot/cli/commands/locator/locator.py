from typer_di import TyperDI

from wtbot.cli.commands.locator import dump, page_numbers, sections, toc

app = TyperDI(
    no_args_is_help=True,
    name="locator",
    help="Resolve back-of-book locators (page numbers, section ids) against "
    "an Index's <pagelist> and <section> tags. See GET /locator-index/* "
    "(wtbot.api.locator_index) for the underlying contract.",
)

app.add_typer(page_numbers.app, rich_help_panel="Locator Index")
app.add_typer(sections.app, rich_help_panel="Locator Index")
app.add_typer(dump.app, rich_help_panel="Locator Index")
app.add_typer(toc.app, rich_help_panel="Locator Index")
