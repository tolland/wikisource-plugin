from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.model import (
    Commit,
    CommitStatus,
    EditJournal,
    FileBlob,
    FileMeta,
    IndexMeta,
    Page,
    Site,
)
from wtbot.model.wiki.namespace import Namespace, NsRole
from wtbot.model.wikisource.proofread_page_meta import (
    ProofreadPageMeta,
    default_short_name,
)

"""PageStore — all SQL for the VFS layers.

Pure data access: no path knowledge, no HTTP, no tree shape. The
mediawiki:// layer and the wikisource:// overlay both sit on top of this,
so it is the one place that knows the Page/EditJournal/FileBlob queries and
the edit-journal write discipline.
"""

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


@dataclass(frozen=True)
class EffectiveState:
    """What the VFS reports for a page, as opposed to what the Page row holds.

    One object rather than two calls because body and revid are answers to the
    same question -- which revision is current for this page -- and a caller
    that can get one without the other can report a body from one revision
    with the identity of another. See [PageStore.effective_state].
    """

    body: str
    revid: int | None

    @property
    def placeholder(self) -> bool:
        """No revision anywhere: never fetched, and never pushed by us."""
        return self.revid is None


def canonical_title(title: str) -> str:
    """MediaWiki treats underscores and spaces as equivalent in titles, so
    the same Index: can reach us in either form — a fetched Page: keeps the
    wiki's literal title (spaces), while a fan-out stub is generated from the
    request title (often underscores). We preserve whatever was stored and
    normalize only while resolving a title to its Page key."""
    return title.replace("_", " ")


def meta_has_image(meta: ProofreadPageMeta | None) -> bool:
    return meta is not None and (
        meta.thumb_url is not None
        or meta.source_image_url is not None
        or meta.raster_path is not None
    )


class PageStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- sites / namespaces ---------------------------------------------------

    def sites(self) -> list[Site]:
        return list(self.session.exec(select(Site)).all())

    def site(self, family: str, code: str) -> Site | None:
        return self.session.exec(
            select(Site).where(Site.family == family, Site.code == code)
        ).first()

    def namespace_by_name(self, site: Site, name: str) -> Namespace | None:
        """Match a title's namespace prefix against this site's namespace
        map (populated from siteinfo). `name` may be the canonical or the
        localized form; '' is the main namespace."""
        return self.session.exec(
            select(Namespace).where(
                Namespace.site_pk == site.pk,
                (Namespace.canonical_name == name) | (Namespace.local_name == name),
            )
        ).first()

    # -- pages ------------------------------------------------------------------

    def page(self, site: Site, title: str) -> Page | None:
        return self.session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == title)
        ).first()

    def index_page(self, site: Site, title: str) -> Page | None:
        """Resolve an Index title with MediaWiki underscore normalization."""
        return self.session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.index,
                func.replace(Page.title, "_", " ") == canonical_title(title),
            )
        ).first()

    def indexes(self, site: Site) -> list[Page]:
        return list(
            self.session.exec(
                select(Page).where(
                    Page.site_pk == site.pk,
                    Page.content_model == PROOFREAD_INDEX_CONTENT_MODEL,
                )
            ).all()
        )

    def proofread_pages(self, site: Site, index_title: str) -> list[Page]:
        """All Page:-namespace members linked to one Index Page key."""
        index = self.index_page(site, index_title)
        if index is None:
            return []
        return list(
            self.session.exec(
                select(Page)
                .join(ProofreadPageMeta, ProofreadPageMeta.page_pk == Page.pk)
                .where(
                    Page.site_pk == site.pk,
                    Page.namespace_role == NsRole.page,
                    ProofreadPageMeta.index_page_pk == index.pk,
                )
            ).all()
        )

    def proofread_page(self, site: Site, title: str, index_title: str) -> Page | None:
        """One Page: title, required to be a member of [index_title] — an
        arbitrary title must not resolve just because it exists on the site."""
        index = self.index_page(site, index_title)
        if index is None:
            return None
        return self.session.exec(
            select(Page)
            .join(ProofreadPageMeta, ProofreadPageMeta.page_pk == Page.pk)
            .where(
                Page.site_pk == site.pk,
                Page.title == title,
                Page.namespace_role == NsRole.page,
                ProofreadPageMeta.index_page_pk == index.pk,
            )
        ).first()

    def proofread_pages_by_titles(
        self, site: Site, titles: list[str], index_title: str
    ) -> list[Page]:
        """Batched [proofread_page] with identical membership filters — bulk
        and individual stat must never disagree."""
        index = self.index_page(site, index_title)
        if index is None:
            return []
        return list(
            self.session.exec(
                select(Page)
                .join(ProofreadPageMeta, ProofreadPageMeta.page_pk == Page.pk)
                .where(
                    Page.site_pk == site.pk,
                    Page.title.in_(titles),
                    Page.namespace_role == NsRole.page,
                    ProofreadPageMeta.index_page_pk == index.pk,
                )
            ).all()
        )

    def pages_with_title_prefix(self, site: Site, prefix: str) -> list[Page]:
        """Pages whose title starts with [prefix], case-sensitively. SQLite's
        LIKE is ASCII-case-insensitive, so it serves as the coarse index scan
        and Python refines to the exact prefix."""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.session.exec(
            select(Page)
            .where(
                Page.site_pk == site.pk,
                Page.title.like(f"{escaped}%", escape="\\"),
            )
            .order_by(Page.title)
        ).all()
        return [p for p in rows if p.title.startswith(prefix)]

    def blob(self, file_page: Page) -> FileBlob | None:
        return self.session.exec(
            select(FileBlob).where(FileBlob.page_pk == file_page.pk)
        ).first()

    # -- per-role metadata extensions ---------------------------------------

    def index_meta(self, page: Page) -> IndexMeta | None:
        return self.session.exec(
            select(IndexMeta).where(IndexMeta.page_pk == page.pk)
        ).first()

    def short_name_taken(self, site_pk: int, short_name: str) -> bool:
        return (
            self.session.exec(
                select(IndexMeta).where(
                    IndexMeta.site_pk == site_pk,
                    IndexMeta.short_name == short_name,
                )
            ).first()
            is not None
        )

    def ensure_index_meta(self, page: Page) -> IndexMeta:
        """Fetch-or-create the IndexMeta row, deriving a default short_name
        from the title. Defaults can collide within a site (same base name,
        different extension), so a numeric suffix deconflicts — the user is
        expected to rename to something friendlier anyway."""
        existing = self.index_meta(page)
        if existing is not None:
            return existing
        base = default_short_name(page.title)
        short = base
        n = 2
        while self.short_name_taken(page.site_pk, short):
            short = f"{base}_{n}"
            n += 1
        meta = IndexMeta(page_pk=page.pk, site_pk=page.site_pk, short_name=short)
        self.session.add(meta)
        self.session.commit()
        self.session.refresh(meta)
        return meta

    def set_index_page_count(self, meta: IndexMeta, page_count: int) -> None:
        """Record the Index's total page count on its IndexMeta row. Staged
        on the session (not committed) so it lands in the caller's fan-out
        transaction alongside the stub rows and child requests."""
        if meta.page_count != page_count:
            meta.page_count = page_count
            self.session.add(meta)

    def proofread_page_meta(self, page: Page) -> ProofreadPageMeta | None:
        return self.session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.page_pk == page.pk)
        ).first()

    def proofread_page_metas_by_pks(
        self, page_pks: list[int]
    ) -> dict[int, ProofreadPageMeta]:
        """Batched proofread metadata lookup for callers that already
        batch their Page query."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.page_pk.in_(page_pks))
        ).all()
        return {row.page_pk: row for row in rows}

    def has_reference_image(self, page: Page) -> bool:
        """A scan reference image is known once the fetch worker stored a
        thumb/source URL (or the raster cache filled a local path)."""
        meta = self.proofread_page_meta(page)
        return meta_has_image(meta)

    def file_meta(self, page: Page) -> FileMeta | None:
        return self.session.exec(
            select(FileMeta).where(FileMeta.page_pk == page.pk)
        ).first()

    # -- edit journal -----------------------------------------------------------

    def effective_state(self, page: Page) -> "EffectiveState":
        """What read()/stat() should report for [page]: body and revid together.

        Together because they answer the same question and must not disagree.
        Page.text and Page.revid are the cached *remote* snapshot, written only
        by the fetch worker; local saves never touch them, or Page stops
        meaning "what is on the wiki" and a refresh loses the diff base. So the
        reported values come from a three-level rule:

            latest uncommitted EditJournal row   (a local save)
            > a successful Commit still ahead of the snapshot
                                                 (we pushed; refetch pending)
            > the Page snapshot itself

        The middle level is not an edge case: fetching is decoupled from
        committing, so every push spends time in it. Reporting a bridged body
        with an un-bridged revid there would tell a client the new text lives
        at the old revision -- and the placeholder flag, which follows revid,
        would call a page we just created non-existent.
        """
        commit = self.latest_successful_commits([page.pk]).get(page.pk)
        return self.effective_state_from(
            page,
            uncommitted_body=self.latest_uncommitted_body(page),
            commit=commit,
        )

    @classmethod
    def effective_state_from(
        cls,
        page: Page,
        *,
        uncommitted_body: str | None,
        commit: "Commit | None",
    ) -> "EffectiveState":
        """The same rule, over values a caller already has.

        The batched paths (stat_bulk, listings) load journals and commits for
        every page in one query each; without this they would either re-query
        per page or -- as the bulk path used to -- restate the rule inline and
        drift from it.
        """
        body = uncommitted_body
        if body is None:
            body = cls.pushed_body_ahead_of_snapshot(commit, page)
        if body is None:
            body = page.text or ""
        return EffectiveState(
            body=body,
            revid=cls.pushed_revid_ahead_of_snapshot(commit, page),
        )

    def effective_body(self, page: Page) -> str:
        return self.effective_state(page).body

    def effective_revid(self, page: Page) -> int | None:
        return self.effective_state(page).revid

    def latest_uncommitted_body(self, page: Page) -> str | None:
        """The most recent local save not yet pushed, if any."""
        latest = self.session.exec(
            select(EditJournal)
            .where(EditJournal.page_pk == page.pk)
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at.desc())
            .limit(1)
        ).first()
        return latest.body if latest is not None else None

    def latest_successful_commits(self, page_pks: list[int]) -> dict[int, Commit]:
        """Batched latest successful Commit per page, feeding the
        pushed-but-not-refetched bridge (see [effective_state])."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(Commit)
            .where(Commit.page_pk.in_(page_pks))
            .where(Commit.status == CommitStatus.success)
            .order_by(Commit.created_at, Commit.pk)
        ).all()
        # Rows are ascending, so the newest commit per page_pk wins.
        return {row.page_pk: row for row in rows}

    @staticmethod
    def pushed_revid_ahead_of_snapshot(commit: Commit | None, page: Page) -> int | None:
        """[commit]'s result_revid while it is ahead of the Page snapshot,
        else the snapshot's own revid. Mirrors [pushed_body_ahead_of_snapshot]
        so body and revid can never disagree about which one is current."""
        if (
            commit is not None
            and commit.result_revid is not None
            and (page.revid is None or page.revid < commit.result_revid)
        ):
            return commit.result_revid
        return page.revid

    @staticmethod
    def pushed_body_ahead_of_snapshot(commit: Commit | None, page: Page) -> str | None:
        """The body of [commit] while it is ahead of the Page snapshot — the
        push succeeded but the refetch that trues Page up hasn't landed yet
        (still queued, or failed). In that window the Commit log is the best
        witness of the remote body; once a fetch writes revid >= result_revid
        this returns None and Page.text takes over, so a later remote edit is
        never shadowed."""
        if commit is None or commit.result_revid is None:
            return None
        if page.revid is not None and page.revid >= commit.result_revid:
            return None
        return commit.submitted_body

    def latest_uncommitted_bodies(self, page_pks: list[int]) -> dict[int, str]:
        """Batched form of [effective_body]'s EditJournal lookup, for call
        sites (stat_bulk) that already batch their Page query and shouldn't
        regress to one EditJournal query per page."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(EditJournal)
            .where(EditJournal.page_pk.in_(page_pks))
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at)
        ).all()
        # Rows are ascending by saved_at, so the last write per page_pk wins.
        return {row.page_pk: row.body for row in rows}

    def append_edit(
        self, page: Page, *, body: str, base_revid: int | None, comment: str | None
    ) -> None:
        """Record a local save: journal row + dirty flag. Never touches
        Page.text (the cached remote body / conflict diff base)."""
        self.session.add(
            EditJournal(
                page_pk=page.pk,
                base_revid=base_revid,
                body=body,
                comment=comment,
            )
        )
        page.dirty = True
        page.local_modified_at = datetime.now(timezone.utc)
        self.session.add(page)
        self.session.commit()
