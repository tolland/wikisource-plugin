import logging
from typing import Any

TRACE = 5
TRACE_LEVEL_NAME = "TRACE"


def _trace(self: logging.Logger, message: object, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


def _root_trace(message: object, *args: Any, **kwargs: Any) -> None:
    logging.log(TRACE, message, *args, **kwargs)


def install_trace_logging() -> None:
    """Register a TRACE logging level below DEBUG."""
    logging.addLevelName(TRACE, TRACE_LEVEL_NAME)
    logging.TRACE = TRACE  # type: ignore[attr-defined]

    if not hasattr(logging.Logger, "trace"):
        logging.Logger.trace = _trace  # type: ignore[attr-defined, method-assign]
    if not hasattr(logging, "trace"):
        logging.trace = _root_trace  # type: ignore[attr-defined]
