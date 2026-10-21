from typer_di import TyperDI

from wtbot.cli.commands.dev import extract_outline, reset, transclusion

app = TyperDI(
    no_args_is_help=True,
    name="dev",
    help="Development utilities and outline generation.",
)

# Both sub-apps expose their commands with fully-qualified names already
# (reset-promotion, extract-outline, ...), so their commands are merged flat
# onto `app` instead of nesting them behind another "reset"/"extract-outline"
# group.
app.registered_commands.extend(reset.app.registered_commands)
app.registered_commands.extend(extract_outline.app.registered_commands)
app.registered_commands.extend(transclusion.app.registered_commands)
