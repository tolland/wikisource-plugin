import logging

from wtbot.log_levels import TRACE
from wtbot.logging_config import (
    LoggingConfig,
    body_limit_bytes,
    configure_logging,
    sqlalchemy_echo,
)


def test_sqlalchemy_echo_from_static_config():
    assert sqlalchemy_echo(LoggingConfig()) is False
    assert sqlalchemy_echo(LoggingConfig(sqlalchemy_echo=True)) is True
    assert sqlalchemy_echo(LoggingConfig(sqlalchemy_echo="debug")) == "debug"


def test_configure_logging_enables_vfs_trace_only():
    configure_logging(LoggingConfig(trace_debug_route_tags=frozenset({"vfs"})))

    assert logging.getLogger("wtbot.api.debug_logging_route.vfs").level == TRACE
    assert logging.getLogger("wtbot.api.debug_logging_route.preview").level != TRACE


def test_configure_logging_enables_sql_debug():
    configure_logging(LoggingConfig(sqlalchemy_echo="debug"))

    assert logging.getLogger("sqlalchemy.engine").level == logging.DEBUG


def test_body_limit_comes_from_static_config():
    assert body_limit_bytes(LoggingConfig(body_limit_bytes=12)) == 12
    assert body_limit_bytes(LoggingConfig(body_limit_bytes=-1)) == 0


def test_logging_config_from_env_overrides_defaults():
    config = LoggingConfig.from_env(
        {
            "WTBOT_LOG_LEVEL": "DEBUG",
            "WTBOT_SQLALCHEMY_ECHO": "debug",
            "WTBOT_TRACE_ALL_DEBUG_ROUTES": "true",
            "WTBOT_TRACE_DEBUG_ROUTE_TAGS": "vfs, preview",
            "WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES": "0",
        }
    )

    assert config.root_level == logging.DEBUG
    assert config.sqlalchemy_echo == "debug"
    assert config.trace_all_debug_routes is True
    assert config.trace_debug_route_tags == frozenset({"vfs", "preview"})
    assert config.body_limit_bytes == 0


def test_logging_config_from_dotenv_reads_file(tmp_path, monkeypatch):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "WTBOT_LOG_LEVEL=WARNING",
                "WTBOT_SQLALCHEMY_ECHO=true",
                "WTBOT_TRACE_DEBUG_ROUTE_TAGS=vfs",
                "WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES=64",
            ]
        )
    )
    for name in (
        "WTBOT_LOG_LEVEL",
        "WTBOT_SQLALCHEMY_ECHO",
        "WTBOT_TRACE_DEBUG_ROUTE_TAGS",
        "WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)

    config = LoggingConfig.from_dotenv(dotenv_path)

    assert config.root_level == logging.WARNING
    assert config.sqlalchemy_echo is True
    assert config.trace_debug_route_tags == frozenset({"vfs"})
    assert config.body_limit_bytes == 64
