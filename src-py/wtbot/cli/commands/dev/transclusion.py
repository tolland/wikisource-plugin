"""Generate and apply editable, nested transclusion proposals."""

from pathlib import Path

import typer
import yaml
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api
from wtbot.transclusion import ApplyTransclusionRequest, ApplyTransclusionResult
from wtbot.work_outline import (
    Generation,
    WorkMetadata,
    dump_proposal,
    extract_pdf,
    load_proposal,
    propose,
    render,
    resolve_pages,
)

app = TyperDI(no_args_is_help=True)


@app.command("propose-transclusion")
def propose_transclusion(
    pdf_filepath: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(..., dir_okay=False),
    depth: int = typer.Option(99, min=1),
    level_type: list[str] | None = typer.Option(
        None, help="Repeat LEVEL=TYPE, e.g. 2=Chapter."
    ),
    title: str | None = typer.Option(None, help="Work title for generated headers."),
    author: str = typer.Option(""),
    translator: str | None = typer.Option(None),
    force: bool = typer.Option(False, help="Replace an existing proposal file."),
) -> None:
    """Extract PDF hierarchy and propose nested wiki pages without editing a wiki."""
    try:
        mapping = {1: "Part", 2: "Chapter", 3: "Section"}
        for option in level_type or []:
            level, kind = option.split("=", 1)
            if int(level) < 1 or not kind.strip():
                raise ValueError(
                    f"Invalid level type {option!r}; expected positive LEVEL=TYPE"
                )
            mapping[int(level)] = kind.strip()
        if output.exists() and not force:
            raise ValueError(
                f"Proposal already exists: {output}; use --force to replace it"
            )
        source = extract_pdf(pdf_filepath)
        proposal = propose(
            source,
            generation=Generation(depth=depth, level_types=mapping),
            metadata=WorkMetadata(
                title=title or "",
                author=author,
                translator=translator,
            ),
        )
        # Structural/path problems are editable diagnostics at proposal time.
        try:
            resolve_pages(proposal)
        except ValueError as exc:
            typer.echo(f"Review required: {exc}", err=True)
        with output.open("w" if force else "x", encoding="utf-8") as stream:
            stream.write(dump_proposal(proposal))
        for diagnostic in proposal.unresolved:
            typer.echo(f"Review required: {diagnostic}", err=True)
        typer.echo(
            f"Wrote {output}; edit it, then run apply-transclusion --structure {output} --root-page Book:Work --dry-run"
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("apply-transclusion")
def apply_transclusion(
    structure: Path = typer.Option(..., exists=True, dir_okay=False),
    root_page: str = typer.Option(
        ..., help="Root wiki title for the generated subpages."
    ),
    index_page: str | None = typer.Option(
        None, help="Defaults to Index:<source PDF filename>."
    ),
    dry_run: bool = typer.Option(
        False, help="Print all destination wikitext without API access or writes."
    ),
    force: bool = typer.Option(
        False, help="Replace existing local destinations; append journal history."
    ),
    label: str = typer.Option(
        "",
        envvar="WTBOT_SITE_LABEL",
        help="Registered site; required unless --dry-run.",
    ),
    api: ApiClient = Depends(get_api),
) -> None:
    """Validate an edited proposal and generate ordinary local journal saves."""
    try:
        proposal = load_proposal(structure)
        pages = render(proposal, root_page=root_page, index_page=index_page)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--structure") from exc
    if dry_run:
        for page in pages:
            typer.echo(f"--- {page.title} ---\n{page.body}")
        typer.echo(f"{len(pages)} page(s); no local or remote edits made.")
        return
    if not label:
        raise typer.BadParameter(
            "Pass --label or set WTBOT_SITE_LABEL", param_hint="--label"
        )
    request = ApplyTransclusionRequest(
        label=label,
        proposal=proposal,
        root_page=root_page,
        index_page=index_page,
        force=force,
    )
    result = ApplyTransclusionResult.model_validate(
        api.post("/dev/transclusion", request.model_dump(mode="json", by_alias=True))
    )
    for destination in result.pages:
        typer.echo(destination.path)
    typer.echo(
        f"Saved {len(result.pages)} local edit(s); use the normal commit workflow to publish."
    )
