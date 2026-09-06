import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from wtbot.log.log_levels import TRACE, install_trace_logging

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEBUG_ROUTE_LOGGER = "wtbot.api.debug_logging_route"
# Every router opts in to DebugLoggingRoute; the tag doubles as the tracing
# switch (WTBOT_TRACE_DEBUG_ROUTE_TAGS). Keep in sync with the routers'
# tags=[...] declarations in wtbot/api/*.py.
KNOWN_DEBUG_ROUTE_TAGS = frozenset(
    {
        "commits",
        "edit-journal",
        "fetch",
        "file-blobs",
        "health",
        "links",
        "namespaces",
        "ocr",
        "page-annotations",
        "page-meta",
        "page-nav",
        "pages",
        "preview",
        "reference-image",
        "sites",
        "vfs",
        "viewer",
    }
)
DOTENV_PATH = Path(".env")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


@dataclass(frozen=True)
class LoggingConfig:
    root_level: int = logging.INFO
    sqlalchemy_echo: bool | str = False
    trace_all_debug_routes: bool = False
    trace_debug_route_tags: Iterable[str] = field(default_factory=frozenset)
    body_limit_bytes: int = 131072
    # Detailed worker-failure log (traceback + upstream HTTP history). Off
    # unless a path is given: it is a debugging aid, not part of normal
    # operation, and it holds more than a status display should.
    failure_log_path: Path | None = None
    failure_log_max_bytes: int = 5 * 1024 * 1024
    failure_log_backups: int = 3

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LoggingConfig":
        e = env if env is not None else os.environ
        default = cls()
        return cls(
            failure_log_path=_get_path(e.get("WTBOT_FAILURE_LOG")),
            failure_log_max_bytes=_get_int(
                e.get("WTBOT_FAILURE_LOG_MAX_BYTES"), default.failure_log_max_bytes
            ),
            failure_log_backups=_get_int(
                e.get("WTBOT_FAILURE_LOG_BACKUPS"), default.failure_log_backups
            ),
            root_level=_get_log_level(e.get("WTBOT_LOG_LEVEL"), default.root_level),
            sqlalchemy_echo=_get_sqlalchemy_echo(
                e.get("WTBOT_SQLALCHEMY_ECHO"), default.sqlalchemy_echo
            ),
            trace_all_debug_routes=_get_bool(
                e.get("WTBOT_TRACE_ALL_DEBUG_ROUTES"),
                default.trace_all_debug_routes,
            ),
            trace_debug_route_tags=_get_tags(e.get("WTBOT_TRACE_DEBUG_ROUTE_TAGS")),
            body_limit_bytes=_get_int(
                e.get("WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES"),
                default.body_limit_bytes,
            ),
        )

    @classmethod
    def from_dotenv(cls, path: Path | str = DOTENV_PATH) -> "LoggingConfig":
        load_dotenv(path, override=False)
        return cls.from_env()


def _get_log_level(value: str | None, default: int) -> int:
    if value is None:
        return default
    if value.isdigit():
        return int(value)
    return logging.getLevelNamesMapping().get(value.upper(), default)


def _get_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _get_sqlalchemy_echo(value: str | None, default: bool | str) -> bool | str:
    if value is None:
        return default
    if value.strip().lower() == "debug":
        return "debug"
    return _get_bool(value, bool(default))


def _get_tags(value: str | None) -> frozenset[str]:
    if value is None:
        return frozenset()
    return frozenset(tag.strip() for tag in value.split(",") if tag.strip())


def _get_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip()).expanduser()


def _get_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Static application logging configuration.
#
# .env overrides:
#   - WTBOT_LOG_LEVEL=DEBUG
#   - WTBOT_SQLALCHEMY_ECHO=true|debug
#   - WTBOT_TRACE_DEBUG_ROUTE_TAGS=vfs,preview
#   - WTBOT_TRACE_ALL_DEBUG_ROUTES=true
#   - WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES=0
#   - WTBOT_FAILURE_LOG=logs/wtbot-failures.log
LOGGING_CONFIG = LoggingConfig.from_dotenv()


def debug_route_logger_name(tag: str) -> str:
    return f"{DEBUG_ROUTE_LOGGER}.{tag}"


def configure_logging(config: LoggingConfig = LOGGING_CONFIG) -> None:
    install_trace_logging()

    # Imported here rather than at module scope: failure_log pulls in the
    # wiki package, and logging_config is imported by nearly everything.
    from wtbot.log.failure_log import configure_failure_log

    configure_failure_log(
        config.failure_log_path,
        max_bytes=config.failure_log_max_bytes,
        backup_count=config.failure_log_backups,
    )

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
