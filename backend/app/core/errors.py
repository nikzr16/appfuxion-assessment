"""Domain errors and the single HTTP handler that maps them to JSON.

Every error response has the shape ``{"error": {"code": "...", "message": "..."}}``.
Services raise these; routers never need try/except boilerplate.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """The resource exists but is not in a state that can answer the request."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"


class UnsupportedMediaError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_media_type"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class LLMError(AppError):
    """The LLM provider failed, or is not configured."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_error"


class LLMOutputError(LLMError):
    """A structured reply did not validate against its schema; ``errors`` says why."""

    code = "llm_invalid_output"

    def __init__(
        self, message: str, *, errors: list[dict[str, Any]], code: str | None = None
    ) -> None:
        super().__init__(message, code=code)
        self.errors = errors


def error_body(
    code: str, message: str, details: object | None = None
) -> dict[str, dict[str, object]]:
    body: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - guarded by registration
        raise exc
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


async def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Framework errors (unknown route, wrong method, ``HTTPException``) get the same shape."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    code = "not_found" if exc.status_code == status.HTTP_404_NOT_FOUND else "http_error"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def request_validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    return JSONResponse(
        status_code=422,
        content=error_body(
            "request_validation_failed",
            "The request is invalid.",
            details=jsonable_encoder(exc.errors()),
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
