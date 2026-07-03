import logging

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from wtbot.api.debug_loggig_route import DebugLoggingRoute
from wtbot.log_levels import TRACE, TRACE_LEVEL_NAME

router = APIRouter(route_class=DebugLoggingRoute)


@router.post("/echo")
async def echo(payload: dict) -> dict:
    return payload


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
    caplog.set_level(logging.DEBUG, logger="wtbot.api.debug_loggig_route")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", json={"value": "secret"})

    assert response.status_code == 200
    assert "TRACE REQUEST BODY" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.anyio
async def test_debug_logging_route_logs_body_at_trace(caplog):
    caplog.set_level(TRACE, logger="wtbot.api.debug_loggig_route")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", json={"value": "visible"})

    assert response.status_code == 200
    assert "TRACE REQUEST BODY (JSON)" in caplog.text
    assert '"value": "visible"' in caplog.text
