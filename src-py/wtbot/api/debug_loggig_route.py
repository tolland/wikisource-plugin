import json
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute

from wtbot.log_levels import TRACE, install_trace_logging
from wtbot.logging_config import body_limit_bytes

install_trace_logging()


def _body_limit() -> int:
    return body_limit_bytes()


def _route_logger(route: APIRoute) -> logging.Logger:
    if route.tags:
        return logging.getLogger(f"{__name__}.{route.tags[0]}")
    return logging.getLogger(f"{__name__}.{route.name}")


def _format_body(body: bytes, content_type: str | None) -> str:
    limit = _body_limit()
    truncated = limit > 0 and len(body) > limit
    visible = body[:limit] if truncated else body

    if "json" in (content_type or "").lower():
        try:
            parsed = json.loads(visible)
            text = json.dumps(parsed, indent=2)
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = visible.decode(errors="replace")
    else:
        text = visible.decode(errors="replace")

    if truncated:
        text += f"\n... truncated {len(body) - limit} bytes ..."
    return text


def _request_target(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    return target


class DebugLoggingRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()
        route_logger = _route_logger(self)

        async def custom_route_handler(request: Request) -> Response:
            if not route_logger.isEnabledFor(TRACE):
                return await original_route_handler(request)

            body_bytes = await request.body()
            content_type = request.headers.get("content-type")
            target = _request_target(request)

            if body_bytes:
                route_logger.trace(
                    "%s %s request body:\n%s",
                    request.method,
                    target,
                    _format_body(body_bytes, content_type),
                )
            else:
                route_logger.trace(
                    "%s %s request body: <empty>",
                    request.method,
                    target,
                )

            response: Response = await original_route_handler(request)
            response_body = getattr(response, "body", None)
            if isinstance(response_body, bytes):
                route_logger.trace(
                    "%s %s response %s body:\n%s",
                    request.method,
                    target,
                    response.status_code,
                    _format_body(response_body, response.media_type),
                )
            else:
                route_logger.trace(
                    "%s %s response %s body: <streaming or unavailable>",
                    request.method,
                    target,
                    response.status_code,
                )
            return response

        return custom_route_handler
