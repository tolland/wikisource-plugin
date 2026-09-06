"""Failure classification and the detailed failure log.

The behaviour under test is the one that made the upstream reliability problem
hard to see: a rate-limit response reaching us disguised as a site-definition
error, with the status code discarded.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from wtbot.log.failure_log import (
    FailureContext,
    configure_failure_log,
    record_failure,
    site_label,
)
from wtbot.wiki.failures import FailureKind, classify, parse_retry_after
from wtbot.wiki.http_tap import (
    HttpExchange,
    clear_exchanges,
    last_http_evidence,
    summarize_query,
)


@pytest.fixture(autouse=True)
def _quiet_tap():
    """The tap is process-global by design; keep one test's requests from
    becoming another's evidence."""
    clear_exchanges()
    yield
    clear_exchanges()


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class _FakeHttpError(Exception):
    def __init__(self, message: str, response):
        super().__init__(message)
        self.response = response


class SiteDefinitionError(Exception):
    """Stands in for pywikibot's, which is what a 429 arrives as. The
    classifier matches on the class *name*, so the name is the fixture."""


class _APIError(Exception):
    def __init__(self, code: str, info: str):
        super().__init__(f"{code}: {info}")
        self.code = code
        self.info = info


def test_classify_reads_status_and_retry_after_from_response():
    exc = _FakeHttpError("too many", _FakeResponse(429, {"retry-after": "12"}))
    failure = classify(exc)
    assert failure.kind is FailureKind.rate_limited
    assert failure.http_status == 429
    assert failure.retry_after == 12.0


def test_classify_treats_ratelimited_api_code_as_rate_limited():
    failure = classify(_APIError("ratelimited", "You've exceeded your rate limit."))
    assert failure.kind is FailureKind.rate_limited


def test_classify_site_definition_error_without_http_evidence():
    """On its own the error says nothing about rate limiting -- and must not
    claim to. The reclassification only happens with wire evidence."""
    failure = classify(SiteDefinitionError("Invalid AutoFamily('en.wikisource.org')"))
    assert failure.kind is FailureKind.site_definition
    assert failure.http_status is None


def test_site_definition_error_reclassified_by_observed_429():
    """The case this whole module exists for: pywikibot converts a non-JSON
    (HTML) rate-limit page into SiteDefinitionError and drops the status code.
    The tap saw the 429, so the verdict is corrected."""
    failure = classify(SiteDefinitionError("Invalid AutoFamily('en.wikisource.org')"))
    refined = failure.with_http(429, 30.0)
    assert refined.kind is FailureKind.rate_limited
    assert refined.http_status == 429
    assert refined.retry_after == 30.0
    assert refined.transient
    assert "429" in refined.summary


def test_classify_page_not_found_is_not_transient():
    from wtbot.wiki.wiki_types import PageNotFound

    failure = classify(PageNotFound("Page:Nope/1"))
    assert failure.kind is FailureKind.not_found
    assert not failure.transient


@pytest.mark.parametrize(
    "header,expected",
    [
        ("12", 12.0),
        ("0.5", 0.5),
        (" 30 ", 30.0),
        ("", None),
        (None, None),
        ("not-a-number", None),
    ],
)
def test_parse_retry_after_seconds_forms(header, expected):
    assert parse_retry_after(header) == expected


def test_parse_retry_after_http_date_form():
    now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
    later = now + timedelta(seconds=60)
    header = later.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(header, now=now) == pytest.approx(60.0, abs=1.0)


def test_last_http_evidence_picks_the_most_recent_failure():
    exchanges = [
        HttpExchange("GET", "en.wikisource.org", "/w/api.php", 200, "", 0.1, None, 0.0),
        HttpExchange("GET", "en.wikisource.org", "/w/api.php", 429, "", 0.1, 45.0, 1.0),
        HttpExchange("GET", "en.wikisource.org", "/w/api.php", 200, "", 0.1, None, 2.0),
    ]
    assert last_http_evidence(exchanges) == (429, 45.0)


def test_last_http_evidence_none_when_nothing_failed():
    ok = [HttpExchange("GET", "h", "/p", 200, "", 0.1, None, 0.0)]
    assert last_http_evidence(ok) == (None, None)


def test_summarize_query_keeps_the_verb_and_drops_the_payload():
    summary = summarize_query(
        "action=query&prop=imageforpage&titles=Page%3ASecret.djvu%2F1&token=abc"
    )
    assert summary == "action=query prop=imageforpage"
    assert "Secret" not in summary and "abc" not in summary


def test_record_failure_writes_detail_file_and_returns_summary(tmp_path, caplog):
    log_path = tmp_path / "failures.log"
    configure_failure_log(log_path)

    context = FailureContext(
        component="fetch",
        title="Page:The principles of mechanics.pdf/51",
        request_pk=2462,
        site_pk=2,
        site_label="wikisource:en @ https://en.wikisource.org/w/api.php",
    )
    with caplog.at_level(logging.WARNING):
        try:
            raise SiteDefinitionError("Invalid AutoFamily")
        except SiteDefinitionError as exc:
            failure = record_failure(context, exc)

    assert failure.summary.startswith("SiteDefinitionError: Invalid AutoFamily")

    written = log_path.read_text("utf-8")
    assert "request_pk=2462" in written
    assert "Page:The principles of mechanics.pdf/51" in written
    assert "Traceback" in written  # the long form the DB column cannot hold
    # ...and a one-line summary still reaches the ordinary application log.
    assert any("request_pk=2462" in r.message for r in caplog.records)


def test_record_failure_survives_a_broken_context(tmp_path):
    """Recording a failure must never raise a second one."""
    configure_failure_log(tmp_path / "failures.log")

    class _Exploding:
        def __str__(self):
            raise RuntimeError("boom")

    context = FailureContext(component="fetch", details={"bad": _Exploding()})
    failure = record_failure(context, ValueError("original problem"))
    assert failure.kind is FailureKind.unknown
    assert "original problem" in failure.summary


def test_site_label_does_not_include_credentials():
    from wtbot.settings import WikiSettings

    settings = WikiSettings(
        family="wikisource",
        code="en",
        api_url="https://en.wikisource.org/w/api.php",
        username="Admin",
        password="hunter2",
    )
    label = site_label(settings)
    assert label == "wikisource:en @ https://en.wikisource.org/w/api.php"
    assert "hunter2" not in label
