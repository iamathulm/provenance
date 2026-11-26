"""Application error types and the single JSON error shape used by every response."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from provenance.core.context import correlation_id_var


def current_correlation_id() -> str:
    return correlation_id_var.get()


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "correlation_id": current_correlation_id()}}
    return JSONResponse(status_code=status_code, content=body)


class AppError(Exception):
    """An expected failure with a stable machine-readable code and a user-safe message."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"


class ForbiddenOriginError(AppError):
    status_code = 403
    code = "origin_not_allowed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered only for AppError
    return error_response(exc.status_code, exc.code, exc.message)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered only for this type
    fields = sorted({".".join(str(part) for part in err["loc"][1:]) for err in exc.errors()})
    return error_response(422, "validation_error", f"Invalid request fields: {', '.join(fields)}")


_HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    """Framework-raised errors (unknown route, wrong method) in the standard error shape."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered only for this type
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    response = error_response(exc.status_code, code, message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
