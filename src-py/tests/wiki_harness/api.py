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

    def create_account(self, username: str, password: str) -> bool:
        """Create an ordinary (non-sysop) account. Returns False if it existed.

        Harness edits should not run as the admin: sysops carry rights that
        change what MediaWiki permits, so testing as admin can hide rejections
        a normal bot account would hit.
        """
        try:
            payload = self._request(
                "POST",
                action="createaccount",
                createtoken=self._token("createaccount"),
                username=username,
                password=password,
                retype=password,
                createreturnurl=self.endpoint.base_url,
            )
        except WikiApiError as exc:
            if exc.code in {"userexists", "acct_creation_throttle_hit"}:
                return False
            raise
        result = payload.get("createaccount", {})
        if result.get("status") != "PASS":
            message = result.get("message") or result.get("messagecode") or result
            if "exists" in str(message):
                return False
            raise WikiApiError("createaccountfailed", str(message))
        return True

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

    def user_exists(self, username: str) -> bool:
        """Whether this wiki has a local account with exactly this name."""
        return self.user_groups(username) is not None

    def user_groups(self, username: str) -> set[str] | None:
        """A local account's groups, or None when the account is absent."""
        payload = self._request(
            "GET", action="query", list="users", ususers=username, usprop="groups"
        )
        user = payload["query"]["users"][0]
        if user.get("missing", False):
            return None
        return set(user.get("groups", []))

    def page_text(self, title: str) -> str | None:
        revisions = self.revisions(title, limit=1, with_content=True)
        return revisions[0].content if revisions else None

    def revisions(
        self, title: str, *, limit: int = 50, with_content: bool = False
    ) -> list[RevisionInfo]:
        """Newest-first revision metadata, optionally with content.

        ``sha1`` is MediaWiki's base-36 encoded hash of the raw revision text --
        the token cross-wiki base discovery would intersect on -- and must not;
        see docs/design/upstream-sync-discussion.md section 3.
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
        # list=proofreadpagesinindex takes only prppiititle/prppiipageid/prppiiprop
        # (https://.../api.php?action=help&modules=query+proofreadpagesinindex) --
        # no limit parameter exists; passing one just draws an "Unrecognized
        # parameter" API warning on every call.
        payload = self._request(
            "GET",
            action="query",
            list="proofreadpagesinindex",
            prppiititle=index_title,
            prppiiprop="ids|title",
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
        baserevid: int | None = None,
        basetimestamp: str | None = None,
        starttimestamp: str | None = None,
    ) -> EditResult:
        """Save a page. The conditional flags are the point of this method --
        they are what section 5.6 of the sync design says every push must carry
        and what the current pywikibot path does not send.

        Prefer ``baserevid`` over ``basetimestamp``: it compares revision ids
        exactly, while ``basetimestamp`` has one-second resolution and cannot
        see an intervening edit made in the same second. ApiEditPage also only
        forwards ``wpEdittime`` when ``baserevid`` is unset, so ``baserevid``
        additionally escapes EditPage's suppress-conflict-with-self branch.
        """
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
        if baserevid is not None:
            params["baserevid"] = str(baserevid)
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
