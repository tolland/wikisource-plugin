"""Page trees pair by literal relative paths, independently of namespaces."""

from dataclasses import dataclass, replace

from sqlmodel import Session, col, select

from wtbot.fetch.revision_store import head_revision
from wtbot.model import Page, Site, Title
from wtbot.sync import SyncPage, SyncVerdict, build_page_report
from wtbot.title_store import canonical_spelling


@dataclass(frozen=True)
class TreeMember:
    path: str
    source_title: str
    target_title: str
    source: Title | None
    target: Title | None


def tree_titles(session: Session, site: Site, root: str) -> dict[str, Title]:
    root = canonical_spelling(root)
    rows = session.exec(
        select(Title).where(
            Title.site_pk == site.pk,
            (Title.title == root)
            | col(Title.title).startswith(root + "/", autoescape=True),
        )
    ).all()
    return {row.title[len(root) :]: row for row in rows}


def members(
    session: Session,
    source_site: Site,
    target_site: Site,
    source_root: str,
    target_root: str,
) -> list[TreeMember]:
    source_root, target_root = map(canonical_spelling, (source_root, target_root))
    source = tree_titles(session, source_site, source_root)
    target = tree_titles(session, target_site, target_root)
    return [
        TreeMember(
            path,
            source_root + path,
            target_root + path,
            source.get(path),
            target.get(path),
        )
        for path in sorted(source.keys() | target.keys() | {""})
    ]


def report_member(
    session: Session, member: TreeMember, source_site: Site, target_site: Site
) -> SyncPage | None:
    source_head = head_revision(
        session, session.get(Page, member.source.pk) if member.source else None
    )
    target_head = head_revision(
        session, session.get(Page, member.target.pk) if member.target else None
    )
    if source_head is None and target_head is None:
        return None
    if member.source is None:
        return SyncPage(
            verdict=SyncVerdict.source_missing,
            page_number=None,
            source_title=member.source_title,
            target_title=member.target_title,
            target_revid=target_head.revid,
            detail="only cached on the target side; fetch the source tree to check",
        )
    row = build_page_report(
        session,
        source_site=source_site,
        target_site=target_site,
        source_title=member.source_title,
        target_title=member.target_title,
    )
    if member.target is None:
        row = replace(
            row,
            verdict=SyncVerdict.unknown,
            detail="target has not been fetched; fetch the mapped title before syncing",
        )
    return row
