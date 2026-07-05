import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from wtbot.log_levels import TRACE, install_trace_logging

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEBUG_ROUTE_LOGGER = "wtbot.api.debug_loggig_route"
KNOWN_DEBUG_ROUTE_TAGS = frozenset({"preview", "vfs"})


@dataclass(frozen=True)
class LoggingConfig:
    root_level: int = logging.INFO
    sqlalchemy_echo: bool | str = False
    trace_all_debug_routes: bool = False
    trace_debug_route_tags: Iterable[str] = field(default_factory=frozenset)
    body_limit_bytes: int = 131072


# Static application logging configuration.
#
# Common edits while debugging:
#   - sqlalchemy_echo=True              logs SQL statements
#   - sqlalchemy_echo="debug"           logs SQL statements and result rows
#   - trace_debug_route_tags={"vfs"}    dumps VFS request/response bodies
#   - trace_all_debug_routes=True       dumps every DebugLoggingRoute body
#   - body_limit_bytes=0                disables body truncation
LOGGING_CONFIG = LoggingConfig()


def debug_route_logger_name(tag: str) -> str:
    return f"{DEBUG_ROUTE_LOGGER}.{tag}"


def configure_logging(config: LoggingConfig = LOGGING_CONFIG) -> None:
    install_trace_logging()

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(config.root_level)
    else:
        logging.basicConfig(
            level=config.root_level,
            format=DEFAULT_LOG_FORMAT,
            datefmt=DEFAULT_LOG_DATE_FORMAT,
        )

    sql_level = logging.NOTSET
    if config.sqlalchemy_echo == "debug":
        sql_level = logging.DEBUG
    elif config.sqlalchemy_echo:
        sql_level = logging.INFO
    logging.getLogger("sqlalchemy.engine").setLevel(sql_level)

    debug_route_level = TRACE if config.trace_all_debug_routes else logging.NOTSET
    logging.getLogger(DEBUG_ROUTE_LOGGER).setLevel(debug_route_level)

    trace_tags = frozenset(config.trace_debug_route_tags)
    configured_tags = KNOWN_DEBUG_ROUTE_TAGS | trace_tags
    for tag in configured_tags:
        level = TRACE if tag in trace_tags else logging.NOTSET
        logging.getLogger(debug_route_logger_name(tag)).setLevel(level)


def sqlalchemy_echo(config: LoggingConfig = LOGGING_CONFIG) -> bool | str:
    return config.sqlalchemy_echo


def body_limit_bytes(config: LoggingConfig = LOGGING_CONFIG) -> int:
    return max(0, config.body_limit_bytes)
