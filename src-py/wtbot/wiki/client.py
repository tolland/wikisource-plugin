import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from wtbot.settings import WikiSettings
from wtbot.wiki.wiki_types import (
    EditConflict,
    IndexPageEntry,
    PageNotFound,
    RemoteChange,
    RemoteFileInfo,
    RemotePage,
    RemotePageImages,
    RenderedPreview,
    SaveResult,
)

"""Wiki access seam.

``WikiClient`` is the interface the worker/endpoints/CLI depend on. ``get_page``
and ``download_file`` are all the fetch path needs. Two implementations:

- ``PywikibotClient`` — real, configured from ``WikiSettings`` (lazy pywikibot
  import so the fake path never loads pywikibot).
- ``FakeWikiClient`` — in-memory, for tests/dev/CLI demos with no network.
"""


log = logging.getLogger(__name__)

#: The props ``prop=imageforpage`` accepts. This is the *whole* parameter
#: surface of that module: ``prop`` (as ``prppifpprop``) and nothing else.
#:
#: We used to also send ``prppifpsize``, meaning to ask for a 240px rendition.
#: No such parameter exists -- ProofreadPage's module defines only ``prop`` --
#: so every one of those requests came back with
#: "API warning (main): Unrecognized parameter: prppifpsize", was served at
#: whatever width the extension chose, and nobody noticed because the warning
#: is not an error and the response still parsed. The thumbnail width is
#: PageDisplayHandler's to decide and is not controllable from here; consumers
#: that need another width rewrite the URL (see /reference-image).
IMAGE_FOR_PAGE_PROPS = "filename|size|fullsize"

#: Titles per pageset query. MediaWiki's limit is 50 without apihighlimits,
#: which an ordinary account does not have.
_TITLES_PER_QUERY = 50


def _chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _https(url: str | None) -> str | None:
    """Normalise the API's protocol-relative //upload... URLs to https://."""
    if url and url.startswith("//"):
        return f"https:{url}"
    return url


def _make_pywikibot_site(pywikibot, settings: WikiSettings):
    """Build a Site without asking pywikibot to scan unrelated families.

    ``Site(url=...)`` first calls ``from_url`` on every configured family.  A
    malformed family loaded into pywikibot's process-global registry can then
    prevent an otherwise valid AutoFamily site from being constructed.  We
    already know that an explicit API URL is an AutoFamily, so construct it
    directly and keep site creation local to these settings.
    """
    if settings.api_url:
        from pywikibot.family import AutoFamily

        family = AutoFamily(settings.family, settings.api_url)
        return pywikibot.Site(code=family.code, fam=family)
    return pywikibot.Site(code=settings.code, fam=settings.family)


@runtime_checkable
class WikiClient(Protocol):
    def get_page(self, title: str) -> RemotePage: ...

    def get_history(self, title: str, *, limit: int) -> list[RemotePage]:
        """Up to ``limit`` revisions of a page, newest first, with content.

        Content is required, not metadata: the whole point is to compare
        against the other site, and a revid alone is not comparable across
        wikis.
        """
        ...

    def list_index_subpage_titles(self, title: str) -> list[str]: ...

    def get_file_info(self, title: str) -> RemoteFileInfo: ...

    def get_page_images(self, title: str) -> RemotePageImages | None:
        """ProofreadPage scan image URLs + proofread quality for a Page:
        title, or None when the wiki/page has none (non-ProofreadPage wikis,
        API errors) -- enrichment, never a fetch-failing call."""
        ...

    def get_page_images_bulk(self, titles: list[str]) -> dict[str, RemotePageImages]:
        """``get_page_images`` for many titles at once.

        Per-title, this is the second request a page fetch costs -- measured,
        it doubled the per-page budget. ``prop=imageforpage`` is a pageset
        module, so fifty titles cost one request instead of fifty. Titles with
        nothing to report are simply absent from the result."""
        ...

    def list_index_pages(self, title: str) -> list[IndexPageEntry] | None:
        """Authoritative pagination of a ProofreadPage index
        (list=proofreadpagesinindex): every slot with its real title, missing
        pages marked by pageid None. None when the API is unavailable --
        callers fall back to page_count interpolation."""
        ...

    def get_default_page_content(self, title: str) -> str | None:
        """The body ProofreadPage would prepopulate the editor with for a
        not-yet-created Page: (pagequality header + the scan's OCR text
        layer + footer, one serialized string), or None when the wiki has
        none to offer -- enrichment, never a fetch-failing call."""
        ...

    def download_file(self, title: str, dest: Path) -> Path: ...

    def get_namespaces(self): ...  # returns pwb NamespacesDict or None

    def recent_changes(
        self,
        *,
        since: datetime,
        namespace_keys: list[int] | None = None,
        limit: int = 5000,
    ) -> list[RemoteChange]: ...

    def oldest_retained_change(self) -> datetime | None:
        """The oldest entry recentchanges still holds, or None if empty.

        The recentchanges table is pruned (``$wgRCMaxAge``, 90 days by
        default), so "nothing changed since X" is indistinguishable from "X is
        older than the wiki remembers" unless you ask. Asking is one request
        and turns a silent wrong answer into a fallback.
        """
        ...

    def save_page(
        self,
        title: str,
        text: str,
        base_revid: int | None,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        """Push a new body for `title`. Raises EditConflict if the page's
        current revid != base_revid (when base_revid is not None), unless
        force=True."""
        ...

    def create_page(
        self,
        title: str,
        text: str,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        """Create `title`, refusing if it already exists unless forced."""
        ...

    def render_preview(
        self, title: str, wikitext: str, content_model: str | None = None
    ) -> RenderedPreview:
        """Render an unsaved body to HTML via ``action=parse`` (preview mode).
        `title` gives templates/magic words their page context; `content_model`
        (e.g. 'proofread-page') selects the ContentHandler when the model can't
        be inferred from the title alone."""
        ...


class PywikibotClient:
    def __init__(self, settings: WikiSettings):
        self.settings = settings
        from wtbot.wiki.config import configure_pywikibot, write_password_entry

        configure_pywikibot(settings)
        import pywikibot

        # Importing the tap imports pywikibot.  It must therefore happen only
        # after configure_pywikibot has disabled repository-local user config;
        # IntelliJ runs with the repository root as its working directory.
        from wtbot.wiki.http_tap import install_http_tap

        install_http_tap()

        self._pwb = pywikibot
        # The configured family name also keeps two AutoFamily wikis on the
        # same host but different ports distinct in pywikibot's Site cache.
        self.site = _make_pywikibot_site(pywikibot, settings)
        # BaseSite.throttle is lazy and snapshots process-global
        # config.minthrottle on first access. Capture it now, while this site's
        # policy is active, so another registered site's client cannot decide
        # this site's pacing merely by being used first.
        _ = self.site.throttle

        # Write the password file entry now that we know the runtime
        # family/code (AutoFamily derives these from the hostname at Site()
        # construction time, so we can't know them before this point).
        # Uses the 4-tuple format so multiple sites in one process each get the
        # right credential rather than the first match winning.
        if settings.username and settings.password:
            import pywikibot.config as pwbconfig

            write_password_entry(
                pwbconfig,
                code=self.site.code,
                family=self.site.family.name,
                settings=settings,
            )
            self.site.login()

        self._log_identity()

    def _log_identity(self) -> None:
        """Record who we are on this wiki, once per client, for free.

        "We thought we were logged in but were not" is invisible in every other
        symptom -- it surfaces later as a commit that cannot save. There is no
        API reporting which rate-limit tier the CDN put us in, so group
        membership -- which the tiers are drawn from, `bot` most decisively --
        is the closest observable proxy.

        Anonymous is not simply "the lower tier": the documented read
        allowance is the same 200 req/min an authenticated account with few
        edits gets, and only an *unidentified* client (no compliant
        User-Agent) drops to 10. But the published table is not the whole
        policy -- Wikimedia's CDN also applies per-IP-block rules, and traffic
        from cloud ranges is treated far less generously than the same request
        from a residential connection, with authentication as the way through.
        So this is INFO rather than a warning about tiers, and it says what is
        actually true: reads may work, and may not, depending on where you are
        calling from; commits will not work at all.

        Reads only what pywikibot already holds. ``site.userinfo`` is a
        property that *fetches* when cold, so asking would spend a request per
        client to log a line about conserving requests. Site construction and a
        successful ``login()`` both populate the cache as a side effect of what
        they were doing anyway, and no credentials means anonymous without
        having to ask -- so both branches are answerable from memory.
        """
        try:
            info = getattr(self.site, "_userinfo", None)
            if not self.settings.username:
                log.info(
                    "wiki client for %s is anonymous: commits will fail, and "
                    "reads depend on how the CDN treats this IP range (cloud "
                    "ranges fare badly). Add an account with "
                    "`wtbot site-credential add`",
                    self.site,
                )
                return
            if not info:
                # Credentials configured but no userinfo cached: the login did
                # not complete. A warning, unlike the branch above -- somebody
                # asked for an identity and did not get it, and the symptom
                # otherwise arrives much later as a commit that cannot save.
                log.warning(
                    "wiki client for %s has credentials for %s but is not "
                    "logged in -- commits will fail",
                    self.site,
                    self.settings.username,
                )
                return
            groups = info.get("groups", [])
            log.info(
                "wiki client for %s logged in as %s (groups=%s, bot_flag=%s)",
                self.site,
                info.get("name"),
                ",".join(g for g in groups if g not in ("*", "user")) or "none",
                "bot" in groups,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics, never fatal
            log.debug("could not read userinfo for %s: %s", self.site, exc)

    def _api_query(self, **params) -> dict | None:
        """Run a read-only API query through pywikibot's authenticated session.

        These queries used to go out as bare ``requests.get`` calls to save
        pywikibot's retry machinery. That traded one problem for a worse one:
        a bare request carries no session cookie, so every one of them was
        *anonymous* even when the client was logged in -- billed against the
        lowest rate-limit tier, with no throttle between them and no
        policy-compliant User-Agent. Three of them per fetched Page: was most
        of our request budget, spent in the way most likely to be limited.

        Through the site, they are throttled, authenticated and identified.
        Fail-soft is preserved by returning None: every caller here is
        enrichment (thumbnails, pagination hints), never the fetch itself. The
        retry concern behind the original comment is handled by config
        max_retries=0 (see wtbot.wiki.config), not by bypassing the session.
        """
        try:
            return self.site.simple_request(**params).submit()
        except Exception as exc:  # noqa: BLE001 - enrichment only, never fatal
            log.debug(
                "api query %s failed on %s: %s",
                params.get("prop") or params.get("list") or params.get("action"),
                self.site,
                exc,
            )
            return None

    def get_page(self, title: str) -> RemotePage:
        """One page, in one upstream request.

        It used to take two. ``page.exists()`` reads ``pageid``, which triggers
        ``loadpageinfo`` (prop=info) on its own; the revision load that follows
        is a second request that carries prop=info anyway and so establishes
        existence by itself -- a missing page raises NoPageError out of it.
        Recorded fan-outs show the cost plainly: 26 info-only requests
        alongside 24 info+revisions requests for one 24-page book, i.e. half
        of the rate-limit budget spent asking a question the next request
        answers. Existence now comes from the revision load.

        ``rev.text`` rather than ``page.text``: identical content (the
        revision was loaded with content=True), but it cannot fall through to
        another fetch, and a redirect is returned as its own wikitext rather
        than raising -- which is what the previous ``page.text`` did too.
        """
        page = self._pwb.Page(self.site, title)
        try:
            rev = page.latest_revision
        except (
            self._pwb.exceptions.NoPageError,
            self._pwb.exceptions.InvalidPageError,
        ) as exc:
            raise PageNotFound(title) from exc
        ns = page.namespace()

        # For Index pages use IndexPage so we get num_pages from the ProofreadPage
        # extension rather than parsing <pagelist> ourselves or relying on file
        # imageinfo metadata (which is absent for many file types).
        page_count = None
        if page.content_model == "proofread-index":
            try:
                from pywikibot.proofreadpage import IndexPage as _IndexPage

                page_count = _IndexPage(self.site, title).num_pages
            except Exception:
                pass

        return RemotePage(
            title=page.title(),
            namespace_key=ns.id,
            namespace_canonical=ns.canonical_name or "",
            # Both are populated by the revision load above (its response
            # carries prop=info), so neither costs a request of its own.
            content_model=page.content_model,
            text=rev.text,
            pageid=getattr(page, "pageid", None),
            revid=rev.revid,
            parentid=rev.parentid,
            timestamp=rev.timestamp,  # pywikibot Timestamp is a datetime subclass
            user=rev.user,
            comment=getattr(rev, "comment", None),
            sha1=rev.sha1,
            size=rev.size,
            page_count=page_count,
        )

    def list_index_subpage_titles(self, title: str) -> list[str]:
        from pywikibot import pagegenerators
        from pywikibot.proofreadpage import IndexPage

        index_page = IndexPage(self.site, title)
        return [
            page.title()
            for page in pagegenerators.PrefixingPageGenerator(
                prefix=f"{title}/",
                site=self.site,
                namespace=index_page.namespace().id,
            )
        ]

    def _resolve_file_page(self, title: str):
        """Resolve a File: title to a FilePage, following the shared repo (e.g.
        Commons) when the file isn't uploaded locally — the common case for
        Wikisource works whose scans live on Wikimedia Commons."""
        filepage = self._pwb.FilePage(self.site, title)
        if filepage.exists():
            return filepage
        shared = self.site.image_repository()
        if shared is not None:
            shared_filepage = self._pwb.FilePage(shared, title)
            if shared_filepage.exists():
                return shared_filepage
        raise PageNotFound(title)

    def get_file_info(self, title: str) -> RemoteFileInfo:
        filepage = self._resolve_file_page(title)
        fi = filepage.latest_file_info
        # Metadata is a list of {name, value} dicts from the MediaWiki API.
        metadata: dict[str, str] = {}
        if fi.metadata:
            for entry in fi.metadata:
                metadata[entry.get("name", "")] = entry.get("value", "")
        page_count_raw = metadata.get("PageCount") or metadata.get("pagecount")
        return RemoteFileInfo(
            title=title,
            file_sha1=fi.sha1,
            size=fi.size,
            mime=fi.mime,
            url=fi.url,
            upload_timestamp=getattr(fi, "timestamp", None),
            uploader=getattr(fi, "user", None),
            upload_comment=getattr(fi, "comment", None),
            page_count=int(page_count_raw) if page_count_raw else None,
            width=getattr(fi, "width", None),
            height=getattr(fi, "height", None),
        )

    def get_page_images(self, title: str) -> RemotePageImages | None:
        # ProofreadPage's module is prop=imageforpage (prefix prppifp), but
        # the *response* key is "imagesforpage"; prop=proofread rides along
        # for the quality level. A miss just means no thumbnail until the next
        # fetch, so this never fails the fetch (see _api_query).
        data = self._api_query(
            action="query",
            prop="imageforpage|proofread",
            titles=title,
            prppifpprop=IMAGE_FOR_PAGE_PROPS,
        )
        if data is None:
            return None
        pages = (data.get("query") or {}).get("pages") or {}
        for pdata in pages.values():
            images = pdata.get("imagesforpage") or {}
            proofread = pdata.get("proofread") or {}
            if not images and not proofread:
                continue
            return RemotePageImages(
                thumbnail_url=_https(images.get("thumbnail")),
                fullsize_url=_https(images.get("fullsize")),
                size=images.get("size"),
                filename=images.get("filename"),
                quality=proofread.get("quality"),
                quality_text=proofread.get("quality_text"),
            )
        return None

    def get_page_images_bulk(self, titles: list[str]) -> dict[str, RemotePageImages]:
        # MediaWiki caps a pageset at 50 titles for a normal account (500 with
        # apihighlimits, which we do not assume), so this chunks rather than
        # asking for a limit we may not have.
        found: dict[str, RemotePageImages] = {}
        for chunk in _chunks(titles, _TITLES_PER_QUERY):
            data = self._api_query(
                action="query",
                prop="imageforpage|proofread",
                titles="|".join(chunk),
                prppifpprop=IMAGE_FOR_PAGE_PROPS,
            )
            if data is None:
                continue
            for pdata in ((data.get("query") or {}).get("pages") or {}).values():
                title = pdata.get("title")
                images = pdata.get("imagesforpage") or {}
                proofread = pdata.get("proofread") or {}
                if not title or (not images and not proofread):
                    continue
                found[title] = RemotePageImages(
                    thumbnail_url=_https(images.get("thumbnail")),
                    fullsize_url=_https(images.get("fullsize")),
                    size=images.get("size"),
                    filename=images.get("filename"),
                    quality=proofread.get("quality"),
                    quality_text=proofread.get("quality_text"),
                )
        return found

    def list_index_pages(self, title: str) -> list[IndexPageEntry] | None:
        # Same fail-soft rationale as get_page_images: this powers fan-out
        # optimisation and placeholder discovery, not correctness -- a miss
        # just means the page_count fallback path.
        #
        # list=proofreadpagesinindex takes only prppiititle/prppiipageid/
        # prppiiprop -- no limit parameter exists (see MediaWiki's own
        # module help), so passing one just draws an "Unrecognized
        # parameter" API warning on every call.
        data = self._api_query(
            action="query",
            list="proofreadpagesinindex",
            prppiititle=title,
            prppiiprop="ids|title",
        )
        if data is None:
            return None
        entries = (data.get("query") or {}).get("proofreadpagesinindex")
        if not isinstance(entries, list):
            return None
        return [
            IndexPageEntry(
                page_offset=e["pageoffset"],
                title=e["title"],
                pageid=e["pageid"] or None,  # the API reports missing as 0
            )
            for e in entries
            if "pageoffset" in e and "title" in e
        ] or None

    def get_default_page_content(self, title: str) -> str | None:
        # ProofreadPage serves the same prepopulated body its own web editor
        # shows on a redlink Page: (pagequality header, the scan's OCR text
        # layer, footer) via prop=defaultcontentforpage — the response value
        # is one serialized string. Same fail-soft rationale as
        # get_page_images: a miss just means the scaffold fallback.
        data = self._api_query(
            action="query",
            prop="defaultcontentforpage",
            titles=title,
        )
        if data is None:
            return None
        pages = (data.get("query") or {}).get("pages") or {}
        for pdata in pages.values():
            content = pdata.get("defaultcontentforpage")
            if isinstance(content, str) and content.strip():
                return content
        return None

    def download_file(self, title: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        filepage = self._resolve_file_page(title)
        filepage.download(filename=str(dest))
        return dest

    def get_namespaces(self):
        return self.site.namespaces

    def save_page(
        self,
        title: str,
        text: str,
        base_revid: int | None,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        page = self._pwb.Page(self.site, title)
        if not force and base_revid is not None and page.exists():
            current_revid = page.latest_revision.revid
            if current_revid != base_revid:
                raise EditConflict(title, base_revid, current_revid)
        page.text = text
        save_options = {"baserevid": base_revid} if not force else {}
        try:
            page.save(summary=comment or "", **save_options)
        except Exception as exc:
            from pywikibot.exceptions import (
                EditConflictError,
                PageCreatedConflictError,
                PageDeletedConflictError,
            )

            if not isinstance(
                exc,
                (
                    EditConflictError,
                    PageCreatedConflictError,
                    PageDeletedConflictError,
                ),
            ):
                raise
            raise EditConflict(title, base_revid or 0, None) from exc
        rev = page.latest_revision
        return SaveResult(revid=rev.revid, timestamp=rev.timestamp)

    def create_page(
        self,
        title: str,
        text: str,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        page = self._pwb.Page(self.site, title)
        page.text = text
        try:
            page.save(summary=comment or "", createonly=not force)
        except Exception as exc:
            from pywikibot.exceptions import (
                ArticleExistsConflictError,
                PageCreatedConflictError,
            )

            if not isinstance(
                exc, (ArticleExistsConflictError, PageCreatedConflictError)
            ):
                raise
            current_revid = page.latest_revision.revid if page.exists() else None
            raise EditConflict(title, 0, current_revid) from exc
        rev = page.latest_revision
        return SaveResult(revid=rev.revid, timestamp=rev.timestamp)

    def render_preview(
        self, title: str, wikitext: str, content_model: str | None = None
    ) -> RenderedPreview:
        params: dict[str, str] = {
            "action": "parse",
            "title": title,
            "text": wikitext,
            "prop": "text",
            "preview": "1",
            "disablelimitreport": "1",
            "disableeditsection": "1",
        }
        if content_model:
            params["contentmodel"] = content_model
        data = self.site.simple_request(**params).submit()
        html = data["parse"]["text"]
        # formatversion=1 wraps the html as {'*': ...}; 2 returns it directly.
        if isinstance(html, dict):
            html = html.get("*", "")
        return RenderedPreview(
            title=title,
            html=html,
            server=f"{self.site.protocol()}://{self.site.hostname()}",
            script_path=self.site.scriptpath(),
        )

    def get_history(self, title: str, *, limit: int) -> list[RemotePage]:
        page = self._pwb.Page(self.site, title)
        if not page.exists():
            raise PageNotFound(title)

        out: list[RemotePage] = []
        namespace = page.namespace()
        for rev in page.revisions(total=limit, content=True):
            out.append(
                RemotePage(
                    title=page.title(),
                    namespace_key=namespace.id,
                    namespace_canonical=namespace.canonical_name or None,
                    content_model=page.content_model,
                    text=rev.text or "",
                    pageid=page.pageid,
                    revid=rev.revid,
                    parentid=rev.parentid or None,
                    timestamp=rev.timestamp,
                    user=rev.user,
                    comment=rev.comment,
                    sha1=rev.sha1,
                    size=rev.size,
                )
            )
        return out

    def recent_changes(
        self,
        *,
        since: datetime,
        namespace_keys: list[int] | None = None,
        limit: int = 5000,
    ) -> list[RemoteChange]:
        """Entries newer than ``since``, oldest first, following continuation.

        ``rcstart`` is inclusive and we scan forwards, so a caller that stores
        the newest timestamp seen and passes it back re-reads that instant's
        entries rather than risking a gap. Refetching a page is idempotent;
        missing one is not.

        There is no ``rcprefix`` -- ``rctitle`` filters to a single page -- so
        narrowing to one work is the caller's job, done on titles we already
        hold. That is a client-side filter over cheap metadata, not a page
        fetch per candidate.
        """
        params: dict[str, str] = {
            "action": "query",
            "list": "recentchanges",
            "rcdir": "newer",
            "rcstart": _api_timestamp(since),
            # Deliberately not `log`: moves and deletions are real sync events
            # (see docs/design/upstream-sync-discussion.md section 5) but they need
            # list=logevents to read properly, and half-reading them here would
            # look like coverage. Edits and creations only.
            "rctype": "edit|new",
            "rcprop": "title|ids|timestamp",
            "rclimit": str(limit),
        }
        if namespace_keys:
            params["rcnamespace"] = "|".join(str(key) for key in sorted(namespace_keys))

        changes: list[RemoteChange] = []
        while True:
            data = self.site.simple_request(**params).submit()
            for entry in data.get("query", {}).get("recentchanges", []):
                change = _change_from_api(entry)
                if change is not None:
                    changes.append(change)
            cont = data.get("continue", {}).get("rccontinue")
            if not cont:
                return changes
            params["rccontinue"] = cont

    def oldest_retained_change(self) -> datetime | None:
        data = self.site.simple_request(
            action="query",
            list="recentchanges",
            rcdir="newer",
            rclimit="1",
            rcprop="timestamp",
        ).submit()
        entries = data.get("query", {}).get("recentchanges", [])
        if not entries:
            return None
        return _parse_api_timestamp(entries[0].get("timestamp"))


def _api_timestamp(moment: datetime) -> str:
    """MediaWiki's ISO-8601-with-Z form, always in UTC.

    A naive datetime is treated as UTC rather than local: every timestamp this
    codebase stores is UTC (see wtbot.timeutil), and guessing the local zone
    here would silently shift the window.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_api_timestamp(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _change_from_api(entry: dict) -> RemoteChange | None:
    timestamp = _parse_api_timestamp(entry.get("timestamp"))
    title = entry.get("title")
    if timestamp is None or not title:
        return None
    return RemoteChange(
        title=title,
        timestamp=timestamp,
        kind=entry.get("type", "edit"),
        pageid=entry.get("pageid") or None,
        revid=entry.get("revid") or None,
        old_revid=entry.get("old_revid") or None,
        namespace_key=entry.get("ns"),
    )


class FakeWikiClient:
    """Network-free WikiClient backed by in-memory dicts."""

    def __init__(
        self,
        pages: dict[str, RemotePage] | None = None,
        files: dict[str, bytes] | None = None,
        page_images: dict[str, RemotePageImages] | None = None,
        index_pages: dict[str, list[IndexPageEntry]] | None = None,
        default_contents: dict[str, str] | None = None,
        changes: list[RemoteChange] | None = None,
        oldest_change: datetime | None = None,
        history: dict[str, list[RemotePage]] | None = None,
    ):
        self._pages = dict(pages or {})
        self._files = dict(files or {})
        self._page_images = dict(page_images or {})
        self._index_pages = dict(index_pages or {})
        self._default_contents = dict(default_contents or {})
        self._changes = sorted(changes or [], key=lambda c: c.timestamp)
        # The retention horizon is set independently of `changes`, because on a
        # real wiki the two are unrelated: recentchanges holds every namespace's
        # entries, while `changes` stands for the handful matching a filter.
        # Deriving one from the other would make every fixture look pruned.
        # None means "holds everything", which is the case most tests want.
        self._oldest_change = oldest_change
        #: title -> revisions newest first, as get_history returns them.
        self._history = dict(history or {})

    def get_page(self, title: str) -> RemotePage:
        try:
            return self._pages[title]
        except KeyError:
            raise PageNotFound(title) from None

    def list_index_subpage_titles(self, title: str) -> list[str]:
        prefix = f"{title}/"
        return sorted(t for t in self._pages if t.startswith(prefix))

    def get_file_info(self, title: str) -> RemoteFileInfo:
        try:
            data = self._files[title]
        except KeyError:
            raise PageNotFound(title) from None
        import hashlib

        sha1 = hashlib.sha1(data).hexdigest()
        ext = title.rsplit(".", 1)[-1].lower() if "." in title else ""
        mime = {
            "djvu": "image/vnd.djvu",
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
        }.get(ext, "application/octet-stream")
        return RemoteFileInfo(
            title=title,
            file_sha1=sha1,
            size=len(data),
            mime=mime,
            url=f"https://fake.wiki/images/{title.split(':', 1)[-1]}",
        )

    def get_page_images(self, title: str) -> RemotePageImages | None:
        return self._page_images.get(title)

    def get_page_images_bulk(self, titles: list[str]) -> dict[str, RemotePageImages]:
        return {t: self._page_images[t] for t in titles if t in self._page_images}

    def list_index_pages(self, title: str) -> list[IndexPageEntry] | None:
        return self._index_pages.get(title)

    def get_default_page_content(self, title: str) -> str | None:
        return self._default_contents.get(title)

    def download_file(self, title: str, dest: Path) -> Path:
        try:
            data = self._files[title]
        except KeyError:
            raise PageNotFound(title) from None
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def get_namespaces(self):
        return None

    def get_history(self, title: str, *, limit: int) -> list[RemotePage]:
        history = self._history.get(title)
        if history is None:
            # A page with no recorded history is one revision deep: its head.
            return [self.get_page(title)]
        return list(history)[:limit]

    def recent_changes(
        self,
        *,
        since: datetime,
        namespace_keys: list[int] | None = None,
        limit: int = 5000,
    ) -> list[RemoteChange]:
        # `since` inclusive, mirroring rcstart.
        selected = [c for c in self._changes if c.timestamp >= since]
        if namespace_keys:
            selected = [c for c in selected if c.namespace_key in set(namespace_keys)]
        return selected[:limit]

    def oldest_retained_change(self) -> datetime | None:
        return self._oldest_change

    def save_page(
        self,
        title: str,
        text: str,
        base_revid: int | None,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        existing = self._pages.get(title)
        current_revid = existing.revid if existing else None
        if not force and base_revid is not None and current_revid != base_revid:
            raise EditConflict(title, base_revid, current_revid)
        new_revid = (current_revid or 0) + 1
        if existing is not None:
            updated = replace(existing, text=text, revid=new_revid, comment=comment)
        else:
            # Mimic what a ProofreadPage wiki reports for a page created by
            # this push: namespace from the title prefix, content model from
            # the namespace, and a real pageid — so refetching a committed
            # placeholder upserts a sensible snapshot.
            ns = title.partition(":")[0] if ":" in title else None
            updated = RemotePage(
                title=title,
                namespace_key=0,
                namespace_canonical=ns,
                content_model={
                    "Page": "proofread-page",
                    "Index": "proofread-index",
                }.get(ns or "", "wikitext"),
                text=text,
                pageid=new_revid + 1000,
                revid=new_revid,
                comment=comment,
            )
        self._pages[title] = updated
        return SaveResult(revid=new_revid, timestamp=updated.timestamp)

    def create_page(
        self,
        title: str,
        text: str,
        comment: str | None,
        *,
        force: bool = False,
    ) -> SaveResult:
        existing = self._pages.get(title)
        if existing is not None and not force:
            raise EditConflict(title, 0, existing.revid)
        return self.save_page(title, text, None, comment, force=force)

    def render_preview(
        self, title: str, wikitext: str, content_model: str | None = None
    ) -> RenderedPreview:
        import html as _html

        return RenderedPreview(
            title=title,
            html=(
                f'<div class="mw-parser-output"><p>{_html.escape(wikitext)}</p></div>'
            ),
        )


def get_wiki_client(settings: WikiSettings) -> WikiClient:
    """Factory used outside tests. Tests inject a FakeWikiClient directly."""
    # inspect(settings)
    return PywikibotClient(settings)
