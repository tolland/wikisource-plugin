from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.model import (
    Commit,
    CommitStatus,
    EditJournal,
    FileBlob,
    FileMeta,
    IndexMeta,
    Site,
    Title,
)
from wtbot.model.wiki.namespace import Namespace, NsRole
from wtbot.model.wikisource.proofread_page_meta import (
    ProofreadPageMeta,
    default_short_name,
)
from wtbot.pages import ResolvedPage, content_of_revision, resolve  # noqa: F401

"""PageStore — all SQL for the VFS layers.

Pure data access: no path knowledge, no HTTP, no tree shape. The
mediawiki:// layer and the wikisource:// overlay both sit on top of this,
so it is the one place that knows the Title/EditJournal/FileBlob queries and
the edit-journal write discipline.
"""

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


@dataclass(frozen=True)
class EffectiveState:
    """What the VFS reports for a page, as opposed to what the Title row holds.

    One object rather than two calls because body and revid are answers to the
    same question -- which revision is current for this page -- and a caller
    that can get one without the other can report a body from one revision
    with the identity of another. See [PageStore.effective_state].
    """

    body: str
    """Never None. Every title has content: the head revision's, a
    pushed-but-unrefetched commit's, a local save, or -- for a paginated page
    nobody has transcribed -- the proposed content MediaWiki itself serves for
    it (the OCR text layer, already wrapped in the pagequality scaffold, which
    ``action=edit&redlink=1`` prefills). That last case is not an empty page;
    it is real content with no revision behind it, which is why the VFS never
    has to ask whether a page exists."""

    revid: int | None
    """The head revid, or None when nothing has been saved at this title yet.

    A value, not missing data -- MediaWiki's ``baserevid`` is optional and its
    absence means "create". Nothing downstream may infer a state from it."""

    modified_at: datetime | None = None

    @property
    def placeholder(self) -> bool:
        """Nothing has ever been saved at this title.

        **Presentation only.** The tool window and the viewer badge an unsaved
        page, and that is the whole of this property's remit. No control flow
        may branch on it: code that needs a revision asks ``wtbot.pages`` for
        one and is refused, with the remedy, if there is none.
        """
        return self.revid is None


def canonical_title(title: str) -> str:
    """MediaWiki treats underscores and spaces as equivalent in titles, so
    the same Index: can reach us in either form — a fetched Page: keeps the
    wiki's literal title (spaces), while a fan-out stub is generated from the
    request title (often underscores). We preserve whatever was stored and
    normalize only while resolving a title to its Title key."""
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

    def page(self, site: Site, title: str) -> Title | None:
        return self.session.exec(
            select(Title).where(Title.site_pk == site.pk, Title.title == title)
        ).first()

    def index_page(self, site: Site, title: str) -> Title | None:
        """Resolve an Index title with MediaWiki underscore normalization."""
        return self.session.exec(
            select(Title).where(
                Title.site_pk == site.pk,
                Title.namespace_role == NsRole.index,
                func.replace(Title.title, "_", " ") == canonical_title(title),
            )
        ).first()

    def indexes(self, site: Site) -> list[Title]:
        """Every Index: we know about on this site.

        Selected by namespace role rather than by ``content_model``: the role
        is a fact about the address and is known for an Index nobody has
        fetched yet, where the content model is only known once one has."""
        return list(
            self.session.exec(
                select(Title).where(
                    Title.site_pk == site.pk,
                    Title.namespace_role == NsRole.index,
                )
            ).all()
        )

    def proofread_pages(self, site: Site, index_title: str) -> list[Title]:
        """All Page:-namespace members linked to one Index Title key."""
        index = self.index_page(site, index_title)
        if index is None:
            return []
        return list(
            self.session.exec(
                select(Title)
                .join(ProofreadPageMeta, ProofreadPageMeta.title_pk == Title.pk)
                .where(
                    Title.site_pk == site.pk,
                    Title.namespace_role == NsRole.page,
                    ProofreadPageMeta.index_page_pk == index.pk,
                )
            ).all()
        )

    def proofread_page(self, site: Site, title: str, index_title: str) -> Title | None:
        """One Page: title, required to be a member of [index_title] — an
        arbitrary title must not resolve just because it exists on the site."""
        index = self.index_page(site, index_title)
        if index is None:
            return None
        return self.session.exec(
            select(Title)
            .join(ProofreadPageMeta, ProofreadPageMeta.title_pk == Title.pk)
            .where(
                Title.site_pk == site.pk,
                Title.title == title,
                Title.namespace_role == NsRole.page,
                ProofreadPageMeta.index_page_pk == index.pk,
            )
        ).first()

    def proofread_pages_by_titles(
        self, site: Site, titles: list[str], index_title: str
    ) -> list[Title]:
        """Batched [proofread_page] with identical membership filters — bulk
        and individual stat must never disagree."""
        index = self.index_page(site, index_title)
        if index is None:
            return []
        return list(
            self.session.exec(
                select(Title)
                .join(ProofreadPageMeta, ProofreadPageMeta.title_pk == Title.pk)
                .where(
                    Title.site_pk == site.pk,
                    Title.title.in_(titles),
                    Title.namespace_role == NsRole.page,
                    ProofreadPageMeta.index_page_pk == index.pk,
                )
            ).all()
        )

    def pages_with_title_prefix(self, site: Site, prefix: str) -> list[Title]:
        """Pages whose title starts with [prefix], case-sensitively. SQLite's
        LIKE is ASCII-case-insensitive, so it serves as the coarse index scan
        and Python refines to the exact prefix."""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.session.exec(
            select(Title)
            .where(
                Title.site_pk == site.pk,
                Title.title.like(f"{escaped}%", escape="\\"),
            )
            .order_by(Title.title)
        ).all()
        return [p for p in rows if p.title.startswith(prefix)]

    def blob(self, file_page: Title) -> FileBlob | None:
        return self.session.exec(
            select(FileBlob).where(FileBlob.title_pk == file_page.pk)
        ).first()

    # -- per-role metadata extensions ---------------------------------------

    def index_meta(self, page: Title) -> IndexMeta | None:
        return self.session.exec(
            select(IndexMeta).where(IndexMeta.title_pk == page.pk)
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

    def ensure_index_meta(self, page: Title) -> IndexMeta:
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
        meta = IndexMeta(title_pk=page.pk, site_pk=page.site_pk, short_name=short)
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

    def proofread_page_meta(self, page: Title) -> ProofreadPageMeta | None:
        return self.session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.title_pk == page.pk)
        ).first()

    def proofread_page_metas_by_pks(
        self, page_pks: list[int]
    ) -> dict[int, ProofreadPageMeta]:
        """Batched proofread metadata lookup for callers that already
        batch their Title query."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.title_pk.in_(page_pks))
        ).all()
        return {row.title_pk: row for row in rows}

    def has_reference_image(self, page: Title) -> bool:
        """A scan reference image is known once the fetch worker stored a
        thumb/source URL (or the raster cache filled a local path)."""
        meta = self.proofread_page_meta(page)
        return meta_has_image(meta)

    def file_meta(self, page: Title) -> FileMeta | None:
        return self.session.exec(
            select(FileMeta).where(FileMeta.title_pk == page.pk)
        ).first()

    # -- edit journal -----------------------------------------------------------

    def effective_state(self, page: Title) -> "EffectiveState":
        """What read()/stat() should report for [page]: body and revid together.

        Together because they answer the same question and must not disagree.
        Nothing local is written into the wiki's own rows: a save appends to
        the journal, and WikiPage/Revision keep meaning "what is on the wiki"
        so a refresh never loses the diff base. The reported values come from
        a four-level rule, in order:

            latest uncommitted EditJournal row   (a local save)
            > a successful Commit still ahead of the head
                                                 (we pushed; refetch pending)
            > the head revision's body           (what the wiki holds)
            > the proposed content               (nothing saved here yet)

        The second level is not an edge case: fetching is decoupled from
        committing, so every push spends time in it. Reporting a bridged body
        with an un-bridged revid there would tell a client the new text lives
        at the old revision -- and the placeholder flag, which follows revid,
        would call a page we just created unsaved.

        The fourth is what makes "virtual pages" unnecessary as a concept.
        MediaWiki serves a body for an untranscribed paginated page, so we
        have one; it simply has no revision behind it, which the revid says.
        """
        commit = self.latest_successful_commits([page.pk]).get(page.pk)
        resolved = resolve(self.session, page)
        head = resolved.head
        content = content_of_revision(self.session, head) if head is not None else None
        return self.effective_state_from(
            page,
            uncommitted_body=self.latest_uncommitted_body(page),
            commit=commit,
            head_revid=resolved.revid,
            head_body=content.text if content is not None else None,
            head_timestamp=head.timestamp if head is not None else None,
            proposed_body=self.proposed_body(page),
        )

    def proposed_body(self, page: Title) -> str | None:
        """What MediaWiki offers as a starting point for this title.

        Stored at index fan-out time (``ProofreadPageMeta.default_body``), so
        serving it is a local read -- the VFS never calls the API to answer a
        read. See the invalidation note in the design: this is derived from
        the index's upload and goes stale if that upload is replaced.
        """
        meta = self.proofread_page_meta(page)
        return meta.default_body if meta is not None else None

    @classmethod
    def effective_state_from(
        cls,
        page: Title,
        *,
        uncommitted_body: str | None,
        commit: "Commit | None",
        head_revid: int | None,
        head_body: str | None = None,
        head_timestamp: "datetime | None" = None,
        proposed_body: str | None = None,
    ) -> "EffectiveState":
        """The same rule, over values a caller already has.

        The batched paths (stat_bulk, listings) load journals, commits and
        resolutions for every page in one query each; without this they would
        either re-query per page or -- as the bulk path used to -- restate the
        rule inline and drift from it.
        """
        body = uncommitted_body
        if body is None:
            body = cls.pushed_body_ahead_of_snapshot(commit, head_revid)
        if body is None:
            body = head_body
        if body is None:
            body = proposed_body
        return EffectiveState(
            body=body or "",
            revid=cls.pushed_revid_ahead_of_snapshot(commit, head_revid),
            modified_at=head_timestamp,
        )

    def effective_body(self, page: Title) -> str:
        return self.effective_state(page).body

    def effective_revid(self, page: Title) -> int | None:
        return self.effective_state(page).revid

    def latest_uncommitted_body(self, page: Title) -> str | None:
        """The most recent local save not yet pushed, if any."""
        latest = self.session.exec(
            select(EditJournal)
            .where(EditJournal.title_pk == page.pk)
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
            .where(Commit.title_pk.in_(page_pks))
            .where(Commit.status == CommitStatus.success)
            .order_by(Commit.created_at, Commit.pk)
        ).all()
        # Rows are ascending, so the newest commit per title_pk wins.
        return {row.title_pk: row for row in rows}

    @staticmethod
    def pushed_revid_ahead_of_snapshot(
        commit: Commit | None, head_revid: int | None
    ) -> int | None:
        """[commit]'s result_revid while it is ahead of the cached head, else
        the head's own revid. Mirrors [pushed_body_ahead_of_snapshot] so body
        and revid can never disagree about which one is current."""
        if (
            commit is not None
            and commit.result_revid is not None
            and (head_revid is None or head_revid < commit.result_revid)
        ):
            return commit.result_revid
        return head_revid

    @staticmethod
    def pushed_body_ahead_of_snapshot(
        commit: Commit | None, head_revid: int | None
    ) -> str | None:
        """The body of [commit] while it is ahead of the cached head — the push
        succeeded but the refetch that trues us up hasn't landed yet (still
        queued, or failed). In that window the Commit log is the best witness
        of the remote body; once a fetch records revid >= result_revid this
        returns None and the head revision takes over, so a later remote edit
        is never shadowed."""
        if commit is None or commit.result_revid is None:
            return None
        if head_revid is not None and head_revid >= commit.result_revid:
            return None
        return commit.submitted_body

    def latest_uncommitted_bodies(self, page_pks: list[int]) -> dict[int, str]:
        """Batched form of [effective_body]'s EditJournal lookup, for call
        sites (stat_bulk) that already batch their Title query and shouldn't
        regress to one EditJournal query per page."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(EditJournal)
            .where(EditJournal.title_pk.in_(page_pks))
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at)
        ).all()
        # Rows are ascending by saved_at, so the last write per title_pk wins.
        return {row.title_pk: row.body for row in rows}

    def append_edit(
        self, page: Title, *, body: str, base_revid: int | None, comment: str | None
    ) -> None:
        """Record a local save: journal row + dirty flag.

        Never touches anything the wiki owns. The journal row's ``saved_at`` is
        when this happened; there is no local timestamp column on Title to
        drift from it."""
        self.session.add(
            EditJournal(
                title_pk=page.pk,
                base_revid=base_revid,
                body=body,
                comment=comment,
            )
        )
        page.dirty = True
        self.session.add(page)
        self.session.commit()
