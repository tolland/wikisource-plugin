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

    assert logging.getLogger("wtbot.api.debug_loggig_route.vfs").level == TRACE
    assert logging.getLogger("wtbot.api.debug_loggig_route.preview").level != TRACE


def test_configure_logging_enables_sql_debug():
    configure_logging(LoggingConfig(sqlalchemy_echo="debug"))

    assert logging.getLogger("sqlalchemy.engine").level == logging.DEBUG


def test_body_limit_comes_from_static_config():
    assert body_limit_bytes(LoggingConfig(body_limit_bytes=12)) == 12
    assert body_limit_bytes(LoggingConfig(body_limit_bytes=-1)) == 0
