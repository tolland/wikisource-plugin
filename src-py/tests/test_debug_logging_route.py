import logging

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Response

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.log_levels import TRACE, TRACE_LEVEL_NAME

router = APIRouter(route_class=DebugLoggingRoute)


@router.post("/echo")
async def echo(payload: dict) -> dict:
    return payload


@router.post("/binary")
async def binary() -> Response:
    return Response(content=b"\x89PNG\r\nhidden-response", media_type="image/png")


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_trace_logging_level_is_registered():
    assert logging.getLevelName(TRACE) == TRACE_LEVEL_NAME
    assert logging.TRACE == TRACE
    assert hasattr(logging.getLogger("wtbot.test"), "trace")


@pytest.mark.anyio
async def test_debug_logging_route_does_not_log_body_at_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="wtbot.api.debug_logging_route")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", json={"value": "secret"})

    assert response.status_code == 200
    assert "request body" not in caplog.text
    assert "response 200 body" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.anyio
async def test_debug_logging_route_logs_body_at_trace(caplog):
    caplog.set_level(TRACE, logger="wtbot.api.debug_logging_route")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", json={"value": "visible"})

    assert response.status_code == 200
    assert "POST /echo request body" in caplog.text
    assert '"value": "visible"' in caplog.text
    assert "POST /echo response 200 body" in caplog.text


@pytest.mark.anyio
async def test_debug_logging_route_summarizes_non_text_bodies(caplog):
    caplog.set_level(TRACE, logger="wtbot.api.debug_logging_route")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/binary",
            content=b"\x00hidden-request\xff",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 200
    assert "POST /binary request body" in caplog.text
    assert "<application/octet-stream; 16 bytes; body not logged>" in caplog.text
    assert "POST /binary response 200 body" in caplog.text
    assert "<image/png; 21 bytes; body not logged>" in caplog.text
    assert "hidden-request" not in caplog.text
    assert "hidden-response" not in caplog.text
