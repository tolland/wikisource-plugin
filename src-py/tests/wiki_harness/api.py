from dataclasses import dataclass
from typing import Any

import requests

from wiki_harness.endpoint import WikiEndpoint
from wtbot.wiki.sha1 import normalize_sha1

"""Thin MediaWiki action-API client for the test harness.

Deliberately not pywikibot: these tests need to drive the *raw* API surface the
sync design depends on -- ``createonly``, ``basetimestamp``, ``undo``, and
per-revision ``sha1`` -- and to assert on the errors it returns. pywikibot
abstracts exactly those away.
"""


class WikiApiError(RuntimeError):
    def __init__(self, code: str, info: str) -> None:
        super().__init__(f"{code}: {info}")
        self.code = code
        self.info = info


@dataclass(frozen=True)
class RevisionInfo:
    revid: int
    parentid: int | None
    timestamp: str
    user: str | None
    comment: str | None
    sha1: str | None  # as the API gives it: 40-char hex
    content: str | None = None

    @property
    def sha1_base36(self) -> str | None:
        """The same digest in the encoding the XML dumps and ``rev_sha1`` use.

        Comparing an API hash straight against a dump hash silently never
        matches -- see wtbot.wiki.sha1.
        """
        return normalize_sha1(self.sha1)


@dataclass(frozen=True)
class EditResult:
    revid: int | None
    title: str
    new: bool


class WikiApi:
    """Authenticated session against one harness wiki."""

    def __init__(self, endpoint: WikiEndpoint) -> None:
        self.endpoint = endpoint
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "wtbot-test-harness"
        self._csrf: str | None = None

    # -- plumbing ---------------------------------------------------------

    def _request(self, method: str, **params: Any) -> dict[str, Any]:
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        if method == "GET":
            response = self._session.get(
                self.endpoint.api_url, params=params, timeout=30
            )
        else:
            response = self._session.post(
                self.endpoint.api_url, data=params, timeout=60
            )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise WikiApiError(
                payload["error"].get("code", "unknown"),
                payload["error"].get("info", ""),
            )
        return payload

    def _token(self, kind: str) -> str:
        payload = self._request("GET", action="query", meta="tokens", type=kind)
        return payload["query"]["tokens"][f"{kind}token"]

    def login(self) -> None:
        """Log in via clientlogin; action=login is restricted to BotPasswords
        on modern MediaWiki and the harness uses the main admin account."""
        payload = self._request(
            "POST",
            action="clientlogin",
            username=self.endpoint.username,
            password=self.endpoint.password,
            loginreturnurl=self.endpoint.base_url,
            logintoken=self._token("login"),
        )
        status = payload.get("clientlogin", {}).get("status")
        if status != "PASS":
            message = payload.get("clientlogin", {}).get("message", status)
            raise WikiApiError("loginfailed", str(message))
        self._csrf = None

    @property
    def csrf_token(self) -> str:
        if self._csrf is None:
            self._csrf = self._token("csrf")
        return self._csrf

    # -- reads ------------------------------------------------------------

    def exists(self, title: str) -> bool:
        payload = self._request("GET", action="query", titles=title)
        pages = payload["query"]["pages"]
        return not pages[0].get("missing", False)

    def page_text(self, title: str) -> str | None:
        revisions = self.revisions(title, limit=1, with_content=True)
        return revisions[0].content if revisions else None

    def revisions(
        self, title: str, *, limit: int = 50, with_content: bool = False
    ) -> list[RevisionInfo]:
        """Newest-first revision metadata, optionally with content.

        ``sha1`` is MediaWiki's base-36 encoded hash of the raw revision text --
        the token the cross-wiki base discovery in docs/upstream-sync-TODO.md
        section 4.2 intersects on.
        """
        props = ["ids", "timestamp", "user", "comment", "sha1"]
        if with_content:
            props.append("content")
        payload = self._request(
            "GET",
            action="query",
            prop="revisions",
            titles=title,
            rvprop="|".join(props),
            rvslots="main",
            rvlimit=limit,
        )
        pages = payload["query"]["pages"]
        if not pages or pages[0].get("missing", False):
            return []
        out: list[RevisionInfo] = []
        for rev in pages[0].get("revisions", []):
            content = None
            if with_content:
                content = rev.get("slots", {}).get("main", {}).get("content")
            out.append(
                RevisionInfo(
                    revid=rev["revid"],
                    parentid=rev.get("parentid") or None,
                    timestamp=rev["timestamp"],
                    user=rev.get("user"),
                    comment=rev.get("comment"),
                    sha1=rev.get("sha1"),
                    content=content,
                )
            )
        return out

    def list_index_pages(self, index_title: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            action="query",
            list="proofreadpagesinindex",
            prppiititle=index_title,
            prppiiprop="ids|title",
            prppiilimit=500,
        )
        return payload.get("query", {}).get("proofreadpagesinindex", [])

    # -- writes -----------------------------------------------------------

    def edit(
        self,
        title: str,
        text: str,
        *,
        summary: str = "harness edit",
        createonly: bool = False,
        nocreate: bool = False,
        basetimestamp: str | None = None,
        starttimestamp: str | None = None,
    ) -> EditResult:
        """Save a page. The conditional flags are the point of this method --
        they are what section 5.6 of the sync design says every push must carry
        and what the current pywikibot path does not send."""
        params: dict[str, Any] = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "token": self.csrf_token,
        }
        if createonly:
            params["createonly"] = "1"
        if nocreate:
            params["nocreate"] = "1"
        if basetimestamp:
            params["basetimestamp"] = basetimestamp
        if starttimestamp:
            params["starttimestamp"] = starttimestamp
        payload = self._request("POST", **params)
        edit = payload["edit"]
        return EditResult(
            revid=edit.get("newrevid"),
            title=edit.get("title", title),
            new="new" in edit,
        )

    def delete(self, title: str, *, reason: str = "harness cleanup") -> None:
        self._request(
            "POST",
            action="delete",
            title=title,
            reason=reason,
            token=self.csrf_token,
        )
