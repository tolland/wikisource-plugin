import logging
import logging.handlers
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from wtbot.wiki.failures import WikiFailure, classify
from wtbot.wiki.http_tap import last_http_evidence, recent_exchanges

"""Detailed failure recording for the fetch and commit workers.

``FetchRequest.error_message`` is one short column, and it is the only thing
the plugin and the viewer ever see. That is the right size for a status
display and far too small to debug an upstream that intermittently rate-limits
us: by the time a row reads ``SiteDefinitionError: Invalid AutoFamily(...)``,
the status code, the URL and the preceding request pattern are all gone.

So failures are recorded twice. The short classified summary goes on the row as
before; the full account -- traceback, request identity, and the outbound HTTP
the tap observed just before the failure -- goes to a separate rotating file,
enabled with ``WTBOT_FAILURE_LOG``. Nothing here can fail a fetch: recording a
failure must not be able to cause one.
"""

FAILURE_LOGGER = "wtbot.failures"

_configured_path: Path | None = None
_configure_lock = threading.Lock()


@dataclass(frozen=True)
class FailureContext:
    """Which piece of work failed. Everything is optional except the component,
    because the two workers know different things about their unit of work."""

    component: str  # 'fetch' | 'commit'
    title: str | None = None
    request_pk: int | None = None
    page_pk: int | None = None
    site_pk: int | None = None
    site_label: str | None = None  # 'wikisource:en @ https://.../api.php'
    details: dict[str, str] = field(default_factory=dict)

    def as_line(self) -> str:
        parts = [f"component={self.component}"]
        for key, value in (
            ("request_pk", self.request_pk),
            ("page_pk", self.page_pk),
            ("site_pk", self.site_pk),
            ("site", self.site_label),
            ("title", self.title),
        ):
            if value is not None:
                parts.append(f"{key}={value!r}" if key == "title" else f"{key}={value}")
        parts.extend(f"{key}={value}" for key, value in sorted(self.details.items()))
        return " ".join(parts)


def site_label(site) -> str:  # noqa: ANN001 - a Site row or a WikiSettings
    """Identify a wiki in a log line without leaking credentials."""
    family = getattr(site, "family", None)
    code = getattr(site, "code", None)
    api_url = getattr(site, "api_url", None)
    label = f"{family}:{code}"
    return f"{label} @ {api_url}" if api_url else label


def configure_failure_log(
    path: Path | str | None,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> Path | None:
    """Point the failure logger at ``path``. Idempotent for the same path, so
    calling it from both ``create_app`` and a CLI entry point is safe. Returns
    the configured path, or None when detail logging is off."""
    global _configured_path
    with _configure_lock:
        if path is None:
            return _configured_path
        target = Path(path)
        if _configured_path == target:
            return target

        logger = logging.getLogger(FAILURE_LOGGER)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        target.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        # The detail file is a destination of its own, not an amplifier of the
        # console: the same failure is already summarised on the app logger.
        logger.propagate = False
        _configured_path = target
        return target


def failure_log_path() -> Path | None:
    return _configured_path


def record_failure(context: FailureContext, exc: BaseException) -> WikiFailure:
    """Classify ``exc``, write the long form, and return the verdict.

    The caller stores ``failure.summary`` on its row. Callers must not need a
    try/except around this -- any error in recording is swallowed and degraded
    to a bare summary, because losing the detail of a failure is bad and
    turning it into a second failure is worse.
    """
    try:
        failure = classify(exc)
        status, retry_after = last_http_evidence()
        failure = failure.with_http(status, retry_after)
        _emit(context, failure, exc)
        return failure
    except Exception:  # noqa: BLE001 - never let logging break the worker
        logging.getLogger(__name__).debug("failure recording failed", exc_info=True)
        return classify(exc)


def _emit(context: FailureContext, failure: WikiFailure, exc: BaseException) -> None:
    headline = f"{context.as_line()} kind={failure.kind.value} {failure.summary}"
    if failure.retry_after is not None:
        headline = f"{headline} retry_after={failure.retry_after:g}s"

    app_log = logging.getLogger(f"wtbot.{context.component}")
    app_log.warning("%s", headline)

    detail = logging.getLogger(FAILURE_LOGGER)
    if not detail.handlers:
        return

    lines = [headline, ""]
    exchanges = recent_exchanges(limit=10)
    if exchanges:
        lines.append("recent upstream requests (oldest first):")
        lines.extend(f"  {exchange}" for exchange in exchanges)
        lines.append("")
    lines.append(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    )
    detail.error("\n".join(lines))
