"""The dedicated log remains useful while a call blocks or fails."""

import logging

import pytest

from wtbot.log.fetch_log import activity, fetch_context, fetch_stage
from wtbot.log.logging_config import LoggingConfig, configure_logging


def test_fetch_file_records_inflight_stage_and_failure_at_warning_level(tmp_path):
    path = tmp_path / "fetch.log"
    config = LoggingConfig(root_level=logging.WARNING, fetch_log_path=path)
    try:
        configure_logging(config)
        configure_logging(config)
        with fetch_context(2191, 1, "Index:Book.pdf"):
            with pytest.raises(RuntimeError, match="upstream failed"):
                with fetch_stage("placeholder_images", "page=1/200"):
                    # Read before the call returns: the start must already be flushed.
                    current = path.read_text()
                    assert "stage=placeholder_images started" in current
                    assert "finished" not in current
                    raise RuntimeError("upstream failed")
        activity("outside request")
        contents = path.read_text()
        assert contents.count("stage=placeholder_images started") == 1
        assert "stage=placeholder_images failed elapsed=" in contents
        assert "request_pk=2191 site_pk=1 title='Index:Book.pdf'" in contents
        assert "page=1/200" in contents
        assert "request_pk=- outside request" in contents
    finally:
        configure_logging(LoggingConfig(fetch_log_path=None))


def test_fetch_log_environment_path_and_console_opt_out():
    assert (
        LoggingConfig.from_env({}).fetch_log_path.as_posix() == "logs/wtbot-fetch.log"
    )
    assert LoggingConfig.from_env({"WTBOT_FETCH_LOG": ""}).fetch_log_path is None
    assert (
        LoggingConfig.from_env(
            {"WTBOT_FETCH_LOG": "/tmp/fetch.log"}
        ).fetch_log_path.as_posix()
        == "/tmp/fetch.log"
    )
