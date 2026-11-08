"""RFC 9457 problem-details errors. Every error response is application/problem+json."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

ERROR_TYPE_BASE = "https://visionguard.ai/errors/"
PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    def __init__(self, status: int, slug: str, title: str, detail: str | None = None,
                 errors: list[dict] | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.errors = errors


def not_found(entity: str) -> ApiError:
    return ApiError(404, "not-found", "Not found", f"{entity} not found")


def forbidden() -> ApiError:
    return ApiError(403, "forbidden", "Forbidden", "You do not have permission to do this")


def conflict(detail: str) -> ApiError:
    return ApiError(409, "conflict", "Conflict", detail)


def problem_response(status: int, slug: str, title: str, detail: str | None = None,
                     errors: list[dict] | None = None, headers: dict | None = None) -> JSONResponse:
    body: dict = {"type": ERROR_TYPE_BASE + slug, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return problem_response(exc.status, exc.slug, exc.title, exc.detail, exc.errors)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return problem_response(422, "validation", "Validation failed", errors=errors)


_HTTP_SLUGS = {401: "unauthorized", 403: "forbidden", 404: "not-found", 405: "method-not-allowed"}


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    slug = _HTTP_SLUGS.get(exc.status_code, "http-error")
    return problem_response(exc.status_code, slug, str(exc.detail), headers=getattr(exc, "headers", None))


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error", exc_info=exc)
    return problem_response(500, "internal", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
