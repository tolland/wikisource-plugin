import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from wtbot.wiki.failures import parse_retry_after

"""A read-only tap on pywikibot's outbound HTTP.

pywikibot performs its own HTTP inside generators and site machinery, so the
only place to see what it really sent is its shared ``requests.Session``. This
installs a response hook on that session and keeps the last N exchanges in a
ring buffer.

Two questions this answers that nothing else could:

- *What was the status code?* pywikibot discards it when it converts a non-JSON
  API response into ``SiteDefinitionError`` (see ``wtbot.wiki.failures``), so
  without this tap a 429 is invisible in the failure record.
- *Which hosts are we actually talking to?* A single ``get_page`` can reach
  Commons or Wikidata through repository resolution, and each of those is a
  request against our rate budget that no caller asked for.

The hook only reads and appends; it never mutates the response or raises into
pywikibot's stack. Bodies are never captured -- status, host, path, the API
``action``/``prop`` and timing are enough to diagnose rate limiting, and
capturing bodies would put page text and login responses in a log file.
"""

log = logging.getLogger(__name__)

DEFAULT_HISTORY = 64

#: Query parameters worth keeping to identify a request. Everything else
#: (titles, tokens, passwords) is dropped.
_INTERESTING_PARAMS = ("action", "list", "prop", "meta", "generator")


@dataclass(frozen=True)
class HttpExchange:
    """One outbound request/response pair, reduced to what diagnoses a stall."""

    method: str
    host: str
    path: str
    status: int
    query_summary: str
    elapsed_seconds: float
    retry_after: float | None
    at: float

    def __str__(self) -> str:
        parts = [
            f"{self.status}",
            f"{self.method} {self.host}{self.path}",
        ]
        if self.query_summary:
            parts.append(f"({self.query_summary})")
        parts.append(f"{self.elapsed_seconds * 1000:.0f}ms")
        if self.retry_after is not None:
            parts.append(f"retry-after={self.retry_after:g}s")
        return " ".join(parts)


class _History:
    """Thread-safe ring buffer. pywikibot's session is shared across threads,
    and the worker may one day drain the queue from more than one."""

    def __init__(self, maxlen: int = DEFAULT_HISTORY) -> None:
        self._lock = threading.Lock()
        self._items: deque[HttpExchange] = deque(maxlen=maxlen)

    def append(self, exchange: HttpExchange) -> None:
        with self._lock:
            self._items.append(exchange)

    def recent(self, limit: int | None = None) -> list[HttpExchange]:
        with self._lock:
            items = list(self._items)
        return items if limit is None else items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_history = _History()
_installed = False
_install_lock = threading.Lock()


def install_http_tap(maxlen: int = DEFAULT_HISTORY) -> bool:
    """Attach the hook to pywikibot's session. Idempotent; returns whether a
    tap is active. False when pywikibot is not importable, which is the normal
    state on the fake-client path."""
    global _installed, _history
    with _install_lock:
        if _installed:
            return True
        try:
            from pywikibot.comms import http as pwb_http
        except Exception:  # noqa: BLE001 - no pywikibot, no tap, no error
            return False

        _history = _History(maxlen)
        hooks = pwb_http.session.hooks.setdefault("response", [])
        if isinstance(hooks, list):
            hooks.append(_on_response)
        else:  # requests allows a bare callable
            pwb_http.session.hooks["response"] = [hooks, _on_response]
        _installed = True
        return True


def _on_response(response, *args, **kwargs) -> None:  # noqa: ANN001 - requests hook
    try:
        _history.append(_exchange_from(response))
    except Exception:  # noqa: BLE001 - diagnostics must never break a fetch
        log.debug("http tap failed to record a response", exc_info=True)


def _exchange_from(response) -> HttpExchange:  # noqa: ANN001 - requests.Response
    parsed = urlparse(response.url)
    return HttpExchange(
        method=response.request.method if response.request is not None else "?",
        host=parsed.netloc,
        path=parsed.path,
        status=response.status_code,
        query_summary=summarize_query(parsed.query),
        elapsed_seconds=response.elapsed.total_seconds() if response.elapsed else 0.0,
        retry_after=parse_retry_after(response.headers.get("retry-after")),
        at=time.time(),
    )


def summarize_query(query: str) -> str:
    """The API verb, without the payload: 'action=query prop=imageforpage'."""
    if not query:
        return ""
    params = parse_qs(query)
    pairs = [
        f"{key}={params[key][0]}" for key in _INTERESTING_PARAMS if params.get(key)
    ]
    return " ".join(pairs)


def recent_exchanges(limit: int | None = None) -> list[HttpExchange]:
    return _history.recent(limit)


def clear_exchanges() -> None:
    _history.clear()


def last_http_evidence(
    exchanges: Iterable[HttpExchange] | None = None,
) -> tuple[int | None, float | None]:
    """Status and Retry-After of the most recent *failed* exchange, for
    attaching to a classified failure. Returns (None, None) when the tap saw
    nothing or everything succeeded -- an exception with no failed request
    behind it was not an HTTP problem."""
    items = list(exchanges) if exchanges is not None else recent_exchanges()
    for exchange in reversed(items):
        if exchange.status >= 400:
            return exchange.status, exchange.retry_after
    return None, None
