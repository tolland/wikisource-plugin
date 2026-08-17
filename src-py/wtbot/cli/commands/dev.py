from typing import Annotated

import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="dev",
    help="Destructive model utilities intended only for development.",
)


def _reset(model: str, force: bool, api: ApiClient) -> None:
    path = f"/dev/{model}"
    plan = api.delete(path) if force else api.get(f"{path}/reset-plan")
    verb = "deleted" if force else "would delete"
    typer.echo(f"{verb}:")
    for entry in plan["counts"]:
        typer.echo(f"  {entry['table']:<20} {entry['rows']:>8}")
    if not force:
        typer.secho(
            f"nothing deleted -- run `wtbot dev reset-{model} --force` to empty "
            "these tables.",
            fg="yellow",
        )


Force = Annotated[
    bool,
    typer.Option(
        "--force",
        help="Actually delete. Without it, only show what would be removed.",
    ),
]


@app.command("reset-promotion")
def reset_promotion(
    force: Force = False,
    api: ApiClient = Depends(get_api),
) -> None:
    """Empty promotion."""
    _reset("promotion", force, api)


@app.command("reset-promotionbatch")
def reset_promotionbatch(
    force: Force = False,
    api: ApiClient = Depends(get_api),
) -> None:
    """Empty promotionbatch and its dependent promotions."""
    _reset("promotionbatch", force, api)


@app.command("reset-fetchrequest")
def reset_fetchrequest(
    force: Force = False,
    api: ApiClient = Depends(get_api),
) -> None:
    """Empty fetchrequest."""
    _reset("fetchrequest", force, api)
