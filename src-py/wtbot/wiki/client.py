"""Wiki access seam.

``WikiClient`` is the interface the worker/endpoints/CLI depend on. ``get_page``
and ``download_file`` are all the fetch path needs. Two implementations:

- ``PywikibotClient`` — real, configured from ``WikiSettings`` (lazy pywikibot
  import so the fake path never loads pywikibot).
- ``FakeWikiClient`` — in-memory, for tests/dev/CLI demos with no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from wtbot.settings import WikiSettings
from wtbot.wiki.types import PageNotFound, RemotePage


@runtime_checkable
class WikiClient(Protocol):
    def get_page(self, title: str) -> RemotePage: ...

    def download_file(self, title: str, dest: Path) -> Path: ...


class PywikibotClient:
    def __init__(self, settings: WikiSettings):
        self.settings = settings
        from wtbot.wiki.config import configure_pywikibot

        configure_pywikibot(settings)
        import pywikibot

        self._pwb = pywikibot
        if settings.api_url:
            self.site = pywikibot.Site(url=settings.api_url)
        else:
            self.site = pywikibot.Site(code=settings.code, fam=settings.family)

    def get_page(self, title: str) -> RemotePage:
        page = self._pwb.Page(self.site, title)
        if not page.exists():
            raise PageNotFound(title)
        rev = page.latest_revision
        ns = page.namespace()
        return RemotePage(
            title=page.title(),
            namespace_key=ns.id,
            namespace_canonical=ns.canonical_name or "",
            content_model=page.content_model,
            text=page.text,
            revid=rev.revid,
            parentid=rev.parentid,
            timestamp=rev.timestamp,  # pywikibot Timestamp is a datetime subclass
            user=rev.user,
            sha1=rev.sha1,
            size=rev.size,
        )

    def download_file(self, title: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        filepage = self._pwb.FilePage(self.site, title)
        if not filepage.exists():
            raise PageNotFound(title)
        filepage.download(filename=str(dest))
        return dest


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

    def download_file(self, title: str, dest: Path) -> Path:
        try:
            data = self._files[title]
        except KeyError:
            raise PageNotFound(title) from None
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest


def get_wiki_client(settings: WikiSettings) -> WikiClient:
    """Factory used outside tests. Tests inject a FakeWikiClient directly."""
    return PywikibotClient(settings)
