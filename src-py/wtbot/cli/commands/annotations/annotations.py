from typer_di import TyperDI

from wtbot.cli.commands.annotations import dump, import_svg, load

app = TyperDI(
    no_args_is_help=True,
    name="annotations",
    help="Dump and load the annotation tables. Everything else in the cache "
    "can be re-fetched from the wiki; boxes, text anchors and the links "
    "between them exist only here, so they are what a rebuild has to carry "
    "across by hand. See wtbot.annotation_transfer for the file format.",
)

app.add_typer(dump.app, rich_help_panel="Annotations")
app.add_typer(load.app, rich_help_panel="Annotations")
app.add_typer(import_svg.app, rich_help_panel="Annotations")
