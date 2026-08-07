import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum

"""Classification of wiki-access failures.

The DB row for a failed fetch/commit holds one short string, so the whole
diagnosis has to survive that squeeze. This module turns an arbitrary exception
into a small typed verdict: what kind of failure it is, the HTTP status behind
it when one can be recovered, and how long the server asked us to wait.

Deliberately duck-typed rather than importing pywikibot: the fake-client path
must stay pywikibot-free (see ``wtbot.wiki.client``), and pywikibot moves its
exception classes between releases. Matching on attributes and class names is
the stable surface.

The load-bearing case is rate limiting. pywikibot 11 raises
``SiteDefinitionError: Invalid AutoFamily(...)`` for *any* non-JSON API
response when the site was built from a URL (``AutoFamily``), which is what a
CDN rate-limit or block page is -- see ``data/api/_requests.py``. The status
code reaches ``pywikibot.debug()`` and goes no further. Left unclassified, a
429 is indistinguishable from a genuinely misconfigured site, which is exactly
the confusion this was written to end; ``wtbot.wiki.http_tap`` supplies the
status code that pywikibot dropped.
"""


class FailureKind(str, Enum):
    """What went wrong, at the granularity a caller can act on."""

    not_found = "not_found"  # the title does not exist
    rate_limited = "rate_limited"  # 429/503: we sent too many requests
    server_error = "server_error"  # 5xx, timeouts, connection failures
    site_definition = "site_definition"  # site/family could not be resolved
    conflict = "conflict"  # edit conflict on write-back
    api_error = "api_error"  # the API answered, with an error
    unknown = "unknown"


#: Kinds whose cause is upstream load rather than a defect in the request. A
#: caller may reasonably run the same request again *later*; nothing here
#: schedules that, and nothing should retry in a tight loop -- a 429 means the
#: throttle is wrong, and retrying is how you make it worse.
TRANSIENT_KINDS = frozenset(
    {FailureKind.rate_limited, FailureKind.server_error, FailureKind.site_definition}
)


@dataclass(frozen=True)
class WikiFailure:
    """A classified failure. ``summary`` is what goes in the DB column."""

    kind: FailureKind
    summary: str
    exception_type: str
    http_status: int | None = None
    retry_after: float | None = None

    @property
    def transient(self) -> bool:
        return self.kind in TRANSIENT_KINDS

    def with_http(self, status: int | None, retry_after: float | None) -> "WikiFailure":
        """Refine with HTTP evidence observed out of band (see http_tap).

        Only ever adds information: a 429 seen on the wire reclassifies an
        opaque ``site_definition`` verdict into the rate limiting it actually
        was, but an already-specific verdict keeps its kind.
        """
        if status is None and retry_after is None:
            return self
        kind = self.kind
        summary = self.summary
        if status in _RATE_LIMIT_STATUSES and kind is not FailureKind.rate_limited:
            kind = FailureKind.rate_limited
            summary = f"{summary} [HTTP {status}]"
        elif status is not None and self.http_status is None:
            summary = f"{summary} [HTTP {status}]"
        return WikiFailure(
            kind=kind,
            summary=summary,
            exception_type=self.exception_type,
            http_status=status if status is not None else self.http_status,
            retry_after=retry_after if retry_after is not None else self.retry_after,
        )


_RATE_LIMIT_STATUSES = frozenset({429, 503})

# Matched against the exception's class name, so a pywikibot release that moves
# or renames a class degrades to `unknown` rather than crashing the classifier.
_KIND_BY_EXCEPTION_NAME: dict[str, FailureKind] = {
    "PageNotFound": FailureKind.not_found,
    "NoPageError": FailureKind.not_found,
    "IsRedirectPageError": FailureKind.not_found,
    "EditConflict": FailureKind.conflict,
    "EditConflictError": FailureKind.conflict,
    "SiteDefinitionError": FailureKind.site_definition,
    "UnknownSiteError": FailureKind.site_definition,
    "UnknownFamilyError": FailureKind.site_definition,
    "ServerError": FailureKind.server_error,
    "FatalServerError": FailureKind.server_error,
    "Server414Error": FailureKind.server_error,
    "Server504Error": FailureKind.server_error,
    "ApiTimeoutError": FailureKind.server_error,
    "TimeoutError": FailureKind.server_error,
    "MaxlagTimeoutError": FailureKind.server_error,
    "ConnectionError": FailureKind.server_error,
    "APIError": FailureKind.api_error,
}

# pywikibot APIError codes that mean "you are going too fast".
_RATE_LIMIT_API_CODES = frozenset({"ratelimited", "maxlag"})


def classify(exc: BaseException) -> WikiFailure:
    """Best-effort verdict on ``exc``. Never raises."""
    name = type(exc).__name__
    status = _http_status(exc)
    retry_after = _retry_after(exc)
    kind = _KIND_BY_EXCEPTION_NAME.get(name, FailureKind.unknown)

    api_code = getattr(exc, "code", None)
    if isinstance(api_code, str) and api_code.lower() in _RATE_LIMIT_API_CODES:
        kind = FailureKind.rate_limited
    if status in _RATE_LIMIT_STATUSES:
        kind = FailureKind.rate_limited
    elif status is not None and status >= 500:
        kind = FailureKind.server_error

    summary = f"{name}: {exc}"
    if status is not None:
        summary = f"{summary} [HTTP {status}]"
    return WikiFailure(
        kind=kind,
        summary=summary,
        exception_type=name,
        http_status=status,
        retry_after=retry_after,
    )


def _http_status(exc: BaseException) -> int | None:
    """The status code, from a requests response if the exception carries one,
    else from the message text (pywikibot formats several as '<code> Server
    Error: ...')."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"\b(4\d\d|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        return parse_retry_after(headers.get("retry-after"))
    except Exception:  # noqa: BLE001 - a malformed header is not a failure
        return None


def parse_retry_after(
    value: str | None, *, now: datetime | None = None
) -> float | None:
    """Seconds to wait, from a ``Retry-After`` header.

    RFC 9110 allows either a delay in seconds or an HTTP-date; Wikimedia sends
    the former, but a date costs three lines to support and silently misreading
    one as "no delay" is the failure mode worth avoiding. Returns None when the
    header is absent or unparseable, so callers can apply their own floor --
    the rate-limit docs say to assume at least five seconds.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (when - reference).total_seconds())
