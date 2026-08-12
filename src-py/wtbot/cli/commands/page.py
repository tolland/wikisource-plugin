import typer
from typer_di import Depends, TyperDI

from wtbot.cli.deps import ApiClient, get_api

app = TyperDI(
    no_args_is_help=True,
    name="page",
    help="Inspect cached pages and their locally-held revision records.",
)


def _revision_summary(revision: dict) -> str:
    bits = [f"revision #{revision['pk']}", f"revid={revision['revid']}"]
    if revision.get("parent_revid") is not None:
        bits.append(f"parent={revision['parent_revid']}")
    if revision.get("timestamp"):
        bits.append(f"timestamp={revision['timestamp']}")
    if revision.get("contributor"):
        bits.append(f"contributor={revision['contributor']}")
    if revision.get("minor"):
        bits.append("minor")
    return " ".join(bits)


def _slot_summary(slot: dict) -> str:
    content = slot["content"]
    bits = [f"slot={slot['role']}"]
    if slot.get("origin_revid") is not None:
        bits.append(f"origin={slot['origin_revid']}")
    bits.extend(
        (
            f"content=#{content['pk']}",
            f"model={content.get('content_model') or '-'}",
            f"size={content['size']}",
            f"sha1={content['content_sha1']}",
        )
    )
    return " ".join(bits)


@app.command("query")
def query(
    title: str | None = typer.Option(None, help="Exact full page title."),
    pk: int | None = typer.Option(
        None, "--pk", "--page-pk", help="Local Page primary key."
    ),
    pageid: int | None = typer.Option(None, help="Site-local MediaWiki page id."),
    revid: int | None = typer.Option(None, help="Cached head revision id."),
    label: str | None = typer.Option(
        None,
        "--label",
        "--site-label",
        help="Optional registered site label.",
    ),
    title_contains: str | None = typer.Option(
        None, "--title-contains", help="Match this text anywhere in the title."
    ),
    namespace_role: str | None = typer.Option(
        None, "--namespace-role", help="Namespace role, such as page or index."
    ),
    content_model: str | None = typer.Option(
        None, "--content-model", help="Remote page content model."
    ),
    limit: int = typer.Option(100, min=1, max=1000),
    api: ApiClient = Depends(get_api),
) -> None:
    """Query Page rows and show revisions joined to their slots and content."""
    params = {
        key: value
        for key, value in {
            "pk": pk,
            "title": title,
            "title_contains": title_contains,
            "pageid": pageid,
            "revid": revid,
            "site_label": label,
            "namespace_role": namespace_role,
            "content_model": content_model,
            "limit": limit,
        }.items()
        if value is not None
    }
    results = api.get("/pages/query", **params)
    if not results:
        typer.echo("no pages matched")
        return

    for result in results:
        page = result["page"]
        site = result.get("site_label") or f"site #{page['site_pk']}"
        typer.echo(
            f"page #{page['pk']} {site}:{page['title']} "
            f"pageid={page.get('pageid')} revid={page.get('revid')} "
            f"model={page.get('content_model') or '-'}"
        )
        if not result["revisions"]:
            typer.echo("  no revisions held")
            continue
        for item in result["revisions"]:
            revision_line = _revision_summary(item["revision"])
            slots = item["slots"]
            if len(slots) == 1:
                typer.echo(f"  {revision_line} | {_slot_summary(slots[0])}")
                continue
            typer.echo(f"  {revision_line} slots={len(slots)}")
            for slot in slots:
                typer.echo(f"    {_slot_summary(slot)}")
