from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, col, select

from wtbot.model import (
    Commit,
    CommitStatus,
    EditJournal,
    FileBlob,
    IndexMeta,
    Page,
    Site,
    Title,
)
from wtbot.model.wiki.namespace import Namespace
from wtbot.model.wikisource.proofread_page_meta import (
    ProofreadPageMeta,
    default_short_name,
)
from wtbot.title_store import Entry, entry_by_pk

"""PageStore — all SQL for the VFS layers.

Pure data access: no path knowledge, no HTTP, no tree shape. The
mediawiki:// layer and the wikisource:// overlay both sit on top of this,
so it is the one place that knows the Title/Page/EditJournal/FileBlob queries
and the edit-journal write discipline.

Its unit is the [Entry]: a title, and the page behind it if the wiki holds
one. Every title we know of is addressable -- an untranscribed ``Page:`` the
index paginates has a title, a scan, proposed content and saves, but no page.
Queries select titles and attach pages by the shared key.

Content models are read off ``Title.expected_content_model``: the fetch sets it
to what the wiki said (``record_fetched_content_model``), so for a title the
wiki holds it *is* the page's model, and for one it does not it is the best we
know.
"""

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"
PROOFREAD_PAGE_CONTENT_MODEL = "proofread-page"


@dataclass(frozen=True)
class EffectiveState:
    """What the VFS reports for a title, as opposed to what any one row holds.

    One object rather than two calls because body and revid are answers to the
    same question -- which revision is current for this title -- and a caller
    that can get one without the other can report a body from one revision
    with the identity of another. See [PageStore.effective_state].
    """

    body: str
    revid: int | None

    @property
    def placeholder(self) -> bool:
        """No revision anywhere: the wiki does not hold it, and we have not
        pushed it. Presentation only (the client badges it); nothing branches
        on it."""
        return self.revid is None


def canonical_title(title: str) -> str:
    """MediaWiki treats underscores and spaces as equivalent in titles, so
    the same Index: can reach us in either form — a fetched Page: keeps the
    wiki's literal title (spaces), while a fan-out title is generated from the
    request title (often underscores). We preserve whatever was stored and
    normalize only while resolving a title."""
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

    # -- titles -----------------------------------------------------------------

    def _entries(self, statement) -> list[Entry]:
        """Run a ``select(Title, Page)`` with the page outer-joined."""
        return [
            Entry(title, page)
            for title, page in self.session.exec(
                statement.outerjoin(Page, col(Page.pk) == col(Title.pk))
            ).all()
        ]

    def _first(self, statement) -> Entry | None:
        rows = self._entries(statement.limit(1))
        return rows[0] if rows else None

    def entry(self, site: Site, title: str) -> Entry | None:
        return self._first(
            select(Title, Page).where(Title.site_pk == site.pk, Title.title == title)
        )

    def entry_by_pk(self, pk: int) -> Entry | None:
        return entry_by_pk(self.session, pk)

    def index_entry(self, site: Site, title: str) -> Entry | None:
        """Resolve an Index title with MediaWiki underscore normalization."""
        return self._first(
            select(Title, Page).where(
                Title.site_pk == site.pk,
                Title.expected_content_model == PROOFREAD_INDEX_CONTENT_MODEL,
                func.replace(Title.title, "_", " ") == canonical_title(title),
            )
        )

    def indexes(self, site: Site) -> list[Entry]:
        return self._entries(
            select(Title, Page).where(
                Title.site_pk == site.pk,
                Title.expected_content_model == PROOFREAD_INDEX_CONTENT_MODEL,
            )
        )

    def _members(self, site: Site, index: Entry):
        return (
            select(Title, Page)
            .join(ProofreadPageMeta, col(ProofreadPageMeta.title_pk) == col(Title.pk))
            .where(
                Title.site_pk == site.pk,
                Title.expected_content_model == PROOFREAD_PAGE_CONTENT_MODEL,
                ProofreadPageMeta.index_title_pk == index.pk,
            )
        )

    def proofread_pages(self, site: Site, index_title: str) -> list[Entry]:
        """Every Page: title the Index paginates, held by the wiki or not."""
        index = self.index_entry(site, index_title)
        if index is None:
            return []
        return self._entries(self._members(site, index))

    def proofread_page(self, site: Site, title: str, index_title: str) -> Entry | None:
        """One Page: title, required to be a member of [index_title] — an
        arbitrary title must not resolve just because it exists on the site."""
        index = self.index_entry(site, index_title)
        if index is None:
            return None
        return self._first(self._members(site, index).where(Title.title == title))

    def proofread_pages_by_titles(
        self, site: Site, titles: list[str], index_title: str
    ) -> list[Entry]:
        """Batched [proofread_page] with identical membership filters — bulk
        and individual stat must never disagree."""
        index = self.index_entry(site, index_title)
        if index is None:
            return []
        return self._entries(
            self._members(site, index).where(col(Title.title).in_(titles))
        )

    def entries_with_title_prefix(self, site: Site, prefix: str) -> list[Entry]:
        """Titles starting with [prefix], case-sensitively. SQLite's LIKE is
        ASCII-case-insensitive, so it serves as the coarse index scan and
        Python refines to the exact prefix."""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self._entries(
            select(Title, Page)
            .where(
                Title.site_pk == site.pk,
                col(Title.title).like(f"{escaped}%", escape="\\"),
            )
            .order_by(Title.title)
        )
        return [row for row in rows if row.name.startswith(prefix)]

    def blob(self, file: Entry) -> FileBlob | None:
        if file.page is None:
            return None
        return self.session.exec(
            select(FileBlob).where(FileBlob.page_pk == file.pk)
        ).first()

    # -- per-role metadata extensions ---------------------------------------

    def index_meta(self, index: Title) -> IndexMeta | None:
        return self.session.get(IndexMeta, index.pk)

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

    def ensure_index_meta(self, index: Title) -> IndexMeta:
        """Fetch-or-create the IndexMeta row, deriving a default short_name
        from the title. Defaults can collide within a site (same base name,
        different extension), so a numeric suffix deconflicts — the user is
        expected to rename to something friendlier anyway."""
        existing = self.index_meta(index)
        if existing is not None:
            return existing
        assert index.pk is not None
        base = default_short_name(index.title)
        short = base
        n = 2
        while self.short_name_taken(index.site_pk, short):
            short = f"{base}_{n}"
            n += 1
        meta = IndexMeta(title_pk=index.pk, site_pk=index.site_pk, short_name=short)
        self.session.add(meta)
        self.session.commit()
        self.session.refresh(meta)
        return meta

    def set_index_page_count(self, meta: IndexMeta, page_count: int) -> None:
        """Record the Index's total page count on its IndexMeta row. Staged
        on the session (not committed) so it lands in the caller's fan-out
        transaction alongside the member titles and child requests."""
        if meta.page_count != page_count:
            meta.page_count = page_count
            self.session.add(meta)

    def proofread_page_meta(self, title_pk: int) -> ProofreadPageMeta | None:
        return self.session.get(ProofreadPageMeta, title_pk)

    def proofread_page_metas_by_pks(
        self, title_pks: list[int]
    ) -> dict[int, ProofreadPageMeta]:
        """Batched proofread metadata lookup for callers that already
        batch their title query."""
        if not title_pks:
            return {}
        rows = self.session.exec(
            select(ProofreadPageMeta).where(
                col(ProofreadPageMeta.title_pk).in_(title_pks)
            )
        ).all()
        return {row.title_pk: row for row in rows}

    def has_reference_image(self, title_pk: int) -> bool:
        """A scan reference image is known once the fetch worker stored a
        thumb/source URL (or the raster cache filled a local path)."""
        return meta_has_image(self.proofread_page_meta(title_pk))

    # -- the body a title reports ---------------------------------------------

    def proposed_body(self, entry: Entry, meta: ProofreadPageMeta | None) -> str:
        """What a title the wiki does not hold opens with: for a proofread
        page, the wiki's prepopulated OCR default (stored at Index fan-out)
        or the content-model scaffold, so a new transcription starts
        well-formed; for anything else, nothing. Never persisted."""
        if (
            entry.page is not None
            or entry.content_model != PROOFREAD_PAGE_CONTENT_MODEL
        ):
            return ""
        return (
            meta.default_body if meta is not None else None
        ) or proofread_page_scaffold()

    def effective_state(self, entry: Entry) -> EffectiveState:
        """What read()/stat() should report for [entry]: body and revid together.

        Together because they answer the same question and must not disagree.
        Page.text and Page.revid are the cached *remote* snapshot, written only
        by the fetch worker; local saves never touch them, or Page stops
        meaning "what is on the wiki" and a refresh loses the diff base. So the
        reported values come from one ordered rule:

            latest uncommitted EditJournal row   (a local save)
            > a successful Commit still ahead of the snapshot
                                                 (we pushed; refetch pending)
            > the Page snapshot itself
            > the proposed body                  (the wiki holds no page)

        The second level is not an edge case: fetching is decoupled from
        committing, so every push spends time in it. Reporting a bridged body
        with an un-bridged revid there would tell a client the new text lives
        at the old revision -- and the placeholder flag, which follows revid,
        would call a page we just created non-existent.
        """
        return self.effective_state_from(
            entry,
            uncommitted_body=self.latest_uncommitted_body(entry.pk),
            commit=self.latest_successful_commits([entry.pk]).get(entry.pk),
            proposed=self.proposed_body(entry, self.proofread_page_meta(entry.pk)),
        )

    @classmethod
    def effective_state_from(
        cls,
        entry: Entry,
        *,
        uncommitted_body: str | None,
        commit: "Commit | None",
        proposed: str,
    ) -> EffectiveState:
        """The same rule, over values a caller already has.

        The batched paths (stat_bulk, listings) load journals, commits and
        metadata for every title in one query each; without this they would
        either re-query per title or restate the rule inline and drift from it.
        """
        body = uncommitted_body
        if body is None:
            body = cls.pushed_body_ahead_of_snapshot(commit, entry.page)
        if body is None and entry.page is not None:
            body = entry.page.text
        return EffectiveState(
            body=body or proposed,
            revid=cls.pushed_revid_ahead_of_snapshot(commit, entry.page),
        )

    def effective_body(self, entry: Entry) -> str:
        return self.effective_state(entry).body

    def effective_revid(self, entry: Entry) -> int | None:
        return self.effective_state(entry).revid

    def latest_uncommitted_body(self, title_pk: int) -> str | None:
        """The most recent local save not yet pushed, if any."""
        latest = self.session.exec(
            select(EditJournal)
            .where(EditJournal.title_pk == title_pk)
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(col(EditJournal.saved_at).desc())
            .limit(1)
        ).first()
        return latest.body if latest is not None else None

    def latest_successful_commits(self, title_pks: list[int]) -> dict[int, Commit]:
        """Batched latest successful Commit per title, feeding the
        pushed-but-not-refetched bridge (see [effective_state])."""
        if not title_pks:
            return {}
        rows = self.session.exec(
            select(Commit)
            .where(col(Commit.title_pk).in_(title_pks))
            .where(Commit.status == CommitStatus.success)
            .order_by(col(Commit.created_at), col(Commit.pk))
        ).all()
        # Rows are ascending, so the newest commit per title wins.
        return {row.title_pk: row for row in rows}

    @staticmethod
    def pushed_revid_ahead_of_snapshot(
        commit: Commit | None, page: Page | None
    ) -> int | None:
        """[commit]'s result_revid while it is ahead of the Page snapshot,
        else the snapshot's own revid. Mirrors [pushed_body_ahead_of_snapshot]
        so body and revid can never disagree about which one is current."""
        revid = page.revid if page is not None else None
        if (
            commit is not None
            and commit.result_revid is not None
            and (revid is None or revid < commit.result_revid)
        ):
            return commit.result_revid
        return revid

    @staticmethod
    def pushed_body_ahead_of_snapshot(
        commit: Commit | None, page: Page | None
    ) -> str | None:
        """The body of [commit] while it is ahead of the Page snapshot — the
        push succeeded but the refetch that trues Page up hasn't landed yet
        (still queued, or failed). In that window the Commit log is the best
        witness of the remote body; once a fetch writes revid >= result_revid
        this returns None and Page.text takes over, so a later remote edit is
        never shadowed."""
        if commit is None or commit.result_revid is None:
            return None
        revid = page.revid if page is not None else None
        if revid is not None and revid >= commit.result_revid:
            return None
        return commit.submitted_body

    def latest_uncommitted_bodies(self, title_pks: list[int]) -> dict[int, str]:
        """Batched form of [latest_uncommitted_body], for call sites
        (stat_bulk) that already batch their title query and shouldn't
        regress to one EditJournal query per title."""
        if not title_pks:
            return {}
        rows = self.session.exec(
            select(EditJournal)
            .where(col(EditJournal.title_pk).in_(title_pks))
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(col(EditJournal.saved_at))
        ).all()
        # Rows are ascending by saved_at, so the last write per title wins.
        return {row.title_pk: row.body for row in rows}

    def append_edit(
        self, entry: Entry, *, body: str, base_revid: int | None, comment: str | None
    ) -> None:
        """Record a local save: journal row + dirty flag, on the title. Never
        touches Page.text (the cached remote body / conflict diff base), and
        needs no Page: a title the wiki does not hold can be saved too."""
        self.session.add(
            EditJournal(
                title_pk=entry.pk,
                base_revid=base_revid,
                body=body,
                comment=comment,
            )
        )
        entry.title.dirty = True
        entry.title.local_modified_at = datetime.now(timezone.utc)
        self.session.add(entry.title)
        self.session.commit()


def proofread_page_scaffold() -> str:
    """Conventional skeleton for a not-yet-created proofread page, matching
    what ProofreadPage's own editor prepopulates: quality "not proofread",
    empty header/body/footer sections."""
    return (
        '<noinclude><pagequality level="1" user="" /></noinclude>'
        "\n\n"
        "<noinclude></noinclude>"
    )
