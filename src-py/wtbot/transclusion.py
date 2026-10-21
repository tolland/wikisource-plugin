"""Apply a proposal as ordinary local journal saves, without remote writes."""

from sqlmodel import Session, select

from wtbot.model import Namespace, Site, Title
from wtbot.title_store import Entry, ensure_title
from wtbot.vfs.paths import title_path
from wtbot.vfs.store import PageStore
from wtbot.work_outline import DocumentModel, TransclusionProposal, render


class ApplyTransclusionRequest(DocumentModel):
    label: str
    proposal: TransclusionProposal
    root_page: str
    index_page: str | None = None
    force: bool = False
    dry_run: bool = False


class AppliedDestination(DocumentModel):
    title: str
    path: str
    body: str


class ApplyTransclusionResult(DocumentModel):
    dry_run: bool
    pages: list[AppliedDestination]


def apply_transclusion(
    session: Session, request: ApplyTransclusionRequest
) -> ApplyTransclusionResult:
    site = session.exec(select(Site).where(Site.label == request.label)).first()
    if site is None:
        raise ValueError(f"No registered site labelled {request.label!r}")
    namespaces = list(
        session.exec(select(Namespace).where(Namespace.site_pk == site.pk)).all()
    )

    def canonical(title: str) -> tuple[str, int]:
        prefix, separator, name = title.partition(":")
        if not separator:
            prefix, name = "", title
        ns = next(
            (
                n
                for n in namespaces
                if prefix.casefold()
                in {n.canonical_name.casefold(), n.local_name.casefold()}
            ),
            None,
        )
        if ns is None:
            raise ValueError(
                f"Unknown namespace {prefix!r}; fetch site namespace metadata first"
            )
        if not ns.subpages:
            raise ValueError(f"Namespace {prefix!r} does not support subpages")
        name = "_".join(name.replace("_", " ").split())
        if ns.case == "first-letter":
            name = name[:1].upper() + name[1:]
        return (f"{ns.local_name}:{name}" if ns.local_name else name), ns.key

    store = PageStore(session)
    rendered = render(
        request.proposal, root_page=request.root_page, index_page=request.index_page
    )
    planned: list[AppliedDestination] = []
    keys: list[int] = []
    existing: list[Entry | None] = []
    known_by_title: dict[str, list[Title]] = {}
    for candidate in session.exec(select(Title).where(Title.site_pk == site.pk)).all():
        try:
            candidate_title, _ = canonical(candidate.title)
        except ValueError:
            continue
        known_by_title.setdefault(candidate_title, []).append(candidate)
    seen: set[str] = set()
    for page in rendered:
        title, key = canonical(page.title)
        if title in seen:
            print("got here 2")
            raise ValueError(f"Duplicate destination {title!r}")
        seen.add(title)
        matches = known_by_title.get(title, [])
        if len(matches) > 1:
            raise ValueError(f"Multiple cached addresses resolve to {title!r}")
        match = matches[0] if matches else None
        entry = store.entry_by_pk(match.pk) if match is not None else None
        if entry is not None and not request.force:
            raise ValueError(
                f"Destination already known locally: {title}; use --force to replace local content"
            )
        if entry is not None and entry.content_model != "wikitext":
            raise ValueError(
                f"Destination {title} has content model {entry.content_model!r}"
            )
        planned.append(
            AppliedDestination(
                title=entry.name if entry else title,
                path=title_path(site.family, site.code, title),
                body=page.body,
            )
        )
        keys.append(key)
        existing.append(entry)
    if not request.dry_run:
        try:
            for page, key, entry in zip(planned, keys, existing, strict=True):
                if entry is None:
                    title_row = ensure_title(
                        session,
                        site_pk=site.pk,
                        title=page.title,
                        expected_content_model="wikitext",
                    )
                    title_row.namespace_key = key
                    entry = Entry(title_row, None)
                store.append_edit(
                    entry,
                    body=page.body,
                    base_revid=entry.revid,
                    comment="Generate transclusion structure",
                    commit=False,
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return ApplyTransclusionResult(dry_run=request.dry_run, pages=planned)
