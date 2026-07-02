import logging
from dataclasses import replace
from pathlib import Path
from typing import Protocol, runtime_checkable

from wtbot.settings import WikiSettings
from wtbot.wiki.wiki_types import (
    EditConflict,
    PageNotFound,
    RemoteFileInfo,
    RemotePage,
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


logging.basicConfig(level=logging.DEBUG)


@runtime_checkable
class WikiClient(Protocol):
    def get_page(self, title: str) -> RemotePage: ...

    def list_index_subpage_titles(self, title: str) -> list[str]: ...

    def get_file_info(self, title: str) -> RemoteFileInfo: ...

    def download_file(self, title: str, dest: Path) -> Path: ...

    def get_namespaces(self): ...  # returns pwb NamespacesDict or None

    def save_page(
        self, title: str, text: str, base_revid: int | None, comment: str | None
    ) -> SaveResult:
        """Push a new body for `title`. Raises EditConflict if the page's
        current revid != base_revid (when base_revid is not None)."""
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

        self._pwb = pywikibot
        if settings.api_url:
            self.site = pywikibot.Site(url=settings.api_url)
        else:
            self.site = pywikibot.Site(code=settings.code, fam=settings.family)

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

    def get_page(self, title: str) -> RemotePage:
        page = self._pwb.Page(self.site, title)
        if not page.exists():
            raise PageNotFound(title)
        rev = page.latest_revision
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
            content_model=page.content_model,
            text=page.text,
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

    def download_file(self, title: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        filepage = self._resolve_file_page(title)
        filepage.download(filename=str(dest))
        return dest

    def get_namespaces(self):
        return self.site.namespaces

    def save_page(
        self, title: str, text: str, base_revid: int | None, comment: str | None
    ) -> SaveResult:
        page = self._pwb.Page(self.site, title)
        if base_revid is not None and page.exists():
            current_revid = page.latest_revision.revid
            if current_revid != base_revid:
                raise EditConflict(title, base_revid, current_revid)
        page.text = text
        page.save(summary=comment or "")
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


class FakeWikiClient:
    """Network-free WikiClient backed by in-memory dicts."""

    def __init__(
        self,
        pages: dict[str, RemotePage] | None = None,
        files: dict[str, bytes] | None = None,
    ):
        self._pages = dict(pages or {})
        self._files = dict(files or {})

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

    def save_page(
        self, title: str, text: str, base_revid: int | None, comment: str | None
    ) -> SaveResult:
        existing = self._pages.get(title)
        current_revid = existing.revid if existing else None
        if base_revid is not None and current_revid != base_revid:
            raise EditConflict(title, base_revid, current_revid)
        new_revid = (current_revid or 0) + 1
        updated = (
            replace(existing, text=text, revid=new_revid, comment=comment)
            if existing is not None
            else RemotePage(
                title=title,
                namespace_key=0,
                namespace_canonical=None,
                content_model="wikitext",
                text=text,
                revid=new_revid,
                comment=comment,
            )
        )
        self._pages[title] = updated
        return SaveResult(revid=new_revid, timestamp=updated.timestamp)

    def render_preview(
        self, title: str, wikitext: str, content_model: str | None = None
    ) -> RenderedPreview:
        import html as _html

        return RenderedPreview(
            title=title,
            html=(
                '<div class="mw-parser-output">'
                f"<p>{_html.escape(wikitext)}</p></div>"
            ),
        )


def get_wiki_client(settings: WikiSettings) -> WikiClient:
    """Factory used outside tests. Tests inject a FakeWikiClient directly."""
    return PywikibotClient(settings)
