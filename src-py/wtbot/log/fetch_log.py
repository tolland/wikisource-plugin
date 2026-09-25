"""Fetch activity timings, correlated across worker and processor calls."""

import logging
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic

log = logging.getLogger("wtbot.fetch.activity")
_request: ContextVar[str] = ContextVar("fetch_request", default="request_pk=-")


class _FetchFileHandler(RotatingFileHandler):
    """Identifies the handler owned by fetch logging during reconfiguration."""


def configure_fetch_log(path: Path | None) -> None:
    """Replace only our handler; repeated application setup must not duplicate it."""
    for handler in list(log.handlers):
        if isinstance(handler, _FetchFileHandler):
            log.removeHandler(handler)
            handler.close()
    log.setLevel(logging.INFO)
    log.propagate = path is None
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _FetchFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)


@contextmanager
def fetch_context(request_pk: int, site_pk: int, title: str) -> Iterator[None]:
    token = _request.set(f"request_pk={request_pk} site_pk={site_pk} title={title!r}")
    try:
        yield
    finally:
        _request.reset(token)


def activity(message: str, *args: object) -> None:
    log.info("%s %s", _request.get(), message % args if args else message)


@contextmanager
def fetch_stage(name: str, detail: str = "") -> Iterator[None]:
    """Emit before blocking work, and time failures as well as successes."""
    started = monotonic()
    activity("stage=%s started %s", name, detail)
    try:
        yield
    except BaseException as err:
        traceback.print_exc()
        activity(
            "stage=%s failed elapsed=%.3fs %s (%s) %s",
            name,
            monotonic() - started,
            detail,
            err,
            type(err).__name__,
        )
        raise
    else:
        activity(
            "stage=%s finished elapsed=%.3fs %s", name, monotonic() - started, detail
        )
