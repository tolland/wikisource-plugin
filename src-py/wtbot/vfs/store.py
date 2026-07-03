from datetime import datetime, timezone

from sqlmodel import Session, select

from wtbot.model import EditJournal, FileBlob, Page, Site
from wtbot.model.namespace import Namespace, NsRole
from wtbot.model.page_meta import FileMeta, IndexMeta, PageMeta, default_short_name

"""PageStore — all SQL for the VFS layers.

Pure data access: no path knowledge, no HTTP, no tree shape. The
mediawiki:// layer and the wikisource:// overlay both sit on top of this,
so it is the one place that knows the Page/EditJournal/FileBlob queries and
the edit-journal write discipline.
"""

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


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
        """All Page:-namespace members of one index."""
        return list(
            self.session.exec(
                select(Page).where(
                    Page.site_pk == site.pk,
                    Page.namespace_role == NsRole.page,
                    Page.index_title == index_title,
                )
            ).all()
        )

    def proofread_page(self, site: Site, title: str, index_title: str) -> Page | None:
        """One Page: title, required to be a member of [index_title] — an
        arbitrary title must not resolve just because it exists on the site."""
        return self.session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.title == title,
                Page.namespace_role == NsRole.page,
                Page.index_title == index_title,
            )
        ).first()

    def proofread_pages_by_titles(
        self, site: Site, titles: list[str], index_title: str
    ) -> list[Page]:
        """Batched [proofread_page] with identical membership filters — bulk
        and individual stat must never disagree."""
        return list(
            self.session.exec(
                select(Page).where(
                    Page.site_pk == site.pk,
                    Page.title.in_(titles),
                    Page.namespace_role == NsRole.page,
                    Page.index_title == index_title,
                )
            ).all()
        )

    def index_linked_assets(self, site: Site, index_title: str) -> list[Page]:
        """Index-namespace pages tied to [index_title] via their index_title
        link (as opposed to being title-wise subpages — see
        MediaWikiVfs.subpages for that half)."""
        return list(
            self.session.exec(
                select(Page)
                .where(
                    Page.site_pk == site.pk,
                    Page.namespace_role == NsRole.index,
                    Page.content_model != PROOFREAD_INDEX_CONTENT_MODEL,
                    Page.index_title == index_title,
                )
                .order_by(Page.title)
            ).all()
        )

    def pages_with_title_prefix(self, site: Site, prefix: str) -> list[Page]:
        """Pages whose title starts with [prefix], case-sensitively. SQLite's
        LIKE is ASCII-case-insensitive, so it serves as the coarse index scan
        and Python refines to the exact prefix."""
        escaped = (
            prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
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

    def page_meta(self, page: Page) -> PageMeta | None:
        return self.session.exec(
            select(PageMeta).where(PageMeta.page_pk == page.pk)
        ).first()

    def file_meta(self, page: Page) -> FileMeta | None:
        return self.session.exec(
            select(FileMeta).where(FileMeta.page_pk == page.pk)
        ).first()

    # -- edit journal -----------------------------------------------------------

    def effective_body(self, page: Page) -> str:
        """The body read()/stat() should report for [page].

        Page.text is the cached *remote* body — written only by the fetch
        worker on refresh from the wiki. Local IDE saves must never touch it,
        or it stops meaning "what's on the wiki" and a refresh silently loses
        the diff base. Instead, a save appends an EditJournal row; this reads
        the most recent uncommitted one back, falling back to Page.text when
        there's nothing uncommitted (never edited locally, or already pushed
        and marked committed).
        """
        latest = self.session.exec(
            select(EditJournal)
            .where(EditJournal.page_pk == page.pk)
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at.desc())
            .limit(1)
        ).first()
        if latest is not None:
            return latest.body
        return page.text or ""

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
