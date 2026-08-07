import logging

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from wtbot.api.errors import ApiError, register_error_handlers

app = FastAPI()
register_error_handlers(app)


@app.get("/coded")
async def coded() -> None:
    raise ApiError(
        status_code=502,
        detail="scan image fetch failed: no scheme",
        code="scan-image-fetch-failed",
    )


@app.get("/plain")
async def plain() -> None:
    raise HTTPException(status_code=404, detail="no such thing")


@app.get("/boom")
async def boom() -> None:
    raise RuntimeError("wires crossed")


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_api_error_returns_the_error_object_and_logs_at_error(caplog):
    caplog.set_level(logging.WARNING, logger="wtbot.api.errors")
    async with _client() as client:
        resp = await client.get("/coded", headers={"X-Request-Id": "abc123"})

    assert resp.status_code == 502
    assert resp.json() == {
        "detail": "scan image fetch failed: no scheme",
        "code": "scan-image-fetch-failed",
        "request_id": "abc123",
    }
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert "GET /coded -> 502 [scan-image-fetch-failed]" in record.getMessage()
    assert "request_id=abc123" in record.getMessage()
    assert "no scheme" in record.getMessage()


@pytest.mark.anyio
async def test_plain_http_exception_gets_default_code_and_warning(caplog):
    caplog.set_level(logging.WARNING, logger="wtbot.api.errors")
    async with _client() as client:
        resp = await client.get("/plain")

    assert resp.status_code == 404
    assert resp.json() == {
        "detail": "no such thing",
        "code": "http-error",
        "request_id": None,
    }
    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "GET /plain -> 404 [http-error]: no such thing" in record.getMessage()


@pytest.mark.anyio
async def test_unhandled_exception_becomes_internal_error_with_traceback(caplog):
    caplog.set_level(logging.WARNING, logger="wtbot.api.errors")
    async with _client() as client:
        resp = await client.get("/boom")

    assert resp.status_code == 500
    assert resp.json() == {
        "detail": "RuntimeError: wires crossed",
        "code": "internal-error",
        "request_id": None,
    }
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None  # traceback logged for the unexpected


@pytest.mark.anyio
async def test_validation_error_is_logged_but_keeps_fastapi_body(caplog):
    caplog.set_level(logging.WARNING, logger="wtbot.api.errors")

    @app.get("/typed")
    async def typed(n: int) -> dict[str, int]:
        return {"n": n}

    async with _client() as client:
        resp = await client.get("/typed", params={"n": "not-a-number"})

    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)  # FastAPI's structured shape
    assert "422 [validation-error]" in caplog.text
