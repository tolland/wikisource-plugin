import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

"""Structured error responses and app-wide error logging.

FastAPI treats ``HTTPException`` as a *handled* error and renders it silently —
uvicorn's access log line ("502 Bad Gateway") is all that reaches stdout, while
the useful ``detail`` goes only to the client. The handlers registered here log
every error response (4xx at WARNING, 5xx at ERROR, unexpected exceptions at
ERROR with traceback) on the ``wtbot.api.errors`` logger, so a failed request
is always visible server-side at default settings.

Error bodies are a defined object the plugin can rely on::

    {"detail": "<human-readable cause>", "code": "<stable-kebab-code>",
     "request_id": "<X-Request-Id echo or null>"}

Raise :class:`ApiError` to attach a stable ``code``; a plain ``HTTPException``
gets ``code="http-error"``. ``request_id`` echoes the client's ``X-Request-Id``
header (the plugin sends one per request) so a plugin log line and a sidecar
log line can be joined on one id.
"""

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"
DEFAULT_ERROR_CODE = "http-error"
INTERNAL_ERROR_CODE = "internal-error"
VALIDATION_ERROR_CODE = "validation-error"


class ApiError(HTTPException):
    """An ``HTTPException`` carrying a stable machine-readable ``code`` so the
    plugin can branch on the failure kind without string-matching ``detail``."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def _request_target(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    return target


def _request_id(request: Request) -> str | None:
    return request.headers.get(REQUEST_ID_HEADER)


def _log_error(
    request: Request, status_code: int, code: str, detail: object, **log_kwargs
) -> None:
    level = logging.ERROR if status_code >= 500 else logging.WARNING
    request_id = _request_id(request)
    logger.log(
        level,
        "%s %s -> %s [%s]%s: %s",
        request.method,
        _request_target(request),
        status_code,
        code,
        f" request_id={request_id}" if request_id else "",
        detail,
        **log_kwargs,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = getattr(exc, "code", DEFAULT_ERROR_CODE)
        _log_error(request, exc.status_code, code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": str(exc.detail),
                "code": code,
                "request_id": _request_id(request),
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> Response:
        # Log, then keep FastAPI's structured 422 body (a list of errors) —
        # the shape pydantic clients and the OpenAPI schema expect.
        _log_error(request, 422, VALIDATION_ERROR_CODE, exc.errors())
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        detail = f"{type(exc).__name__}: {exc}"
        _log_error(request, 500, INTERNAL_ERROR_CODE, detail, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": detail,
                "code": INTERNAL_ERROR_CODE,
                "request_id": _request_id(request),
            },
        )
