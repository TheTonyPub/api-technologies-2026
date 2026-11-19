"""Единый формат ошибок платформы (contracts: схема Error) и сквозной X-Request-Id.

Использование в REST-сервисе:
    from platform_common.errors import ApiError, install
    app = FastAPI(...); install(app)
    raise ApiError(404, "COMPANY_NOT_FOUND", "Компания с таким ИНН не найдена")
"""
import logging
import uuid

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("platform")
access_log = logging.getLogger("uvicorn.error.platform")

INN_PATTERN = r"^[0-9]{10}$"

# коды из contracts/*/openapi.yaml
CODES = {"INVALID_REQUEST", "UNAUTHORIZED", "COMPANY_NOT_FOUND",
         "INTERNAL_ERROR", "SERVICE_UNAVAILABLE", "UPSTREAM_TIMEOUT"}

_HTTP_TO_CODE = {400: "INVALID_REQUEST", 401: "UNAUTHORIZED", 404: "INVALID_REQUEST",
                 405: "INVALID_REQUEST", 503: "SERVICE_UNAVAILABLE", 504: "UPSTREAM_TIMEOUT"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_body(code: str, message: str, trace_id: str, details: list | None = None) -> dict:
    body = {"code": code, "message": message, "traceId": trace_id}
    if details:
        body["details"] = details
    return body


def _rid(request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _respond(request, status: int, code: str, message: str, details=None) -> JSONResponse:
    rid = _rid(request)
    return JSONResponse(status_code=status, content=error_body(code, message, rid, details),
                        headers={"X-Request-Id": rid})


def install(app: FastAPI) -> None:
    """Подключает X-Request-Id (берём из запроса или генерируем) и единый формат ошибок."""

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:  # любой необработанный сбой -> 500 в нашем формате
            log.exception("необработанная ошибка, X-Request-Id=%s", rid)
            return JSONResponse(status_code=500, headers={"X-Request-Id": rid},
                                content=error_body("INTERNAL_ERROR", "Внутренняя ошибка сервиса", rid))
        response.headers["X-Request-Id"] = rid
        route = getattr(request.scope.get("route"), "path", "-")
        access_log.info("%s %s %s status=%d X-Request-Id=%r",
                        app.title, request.method, route, response.status_code, rid)
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request, exc: ApiError):
        return _respond(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc: RequestValidationError):
        details = [{"field": str(e["loc"][-1]), "problem": e["msg"]} for e in exc.errors()]
        return _respond(request, 400, "INVALID_REQUEST", "Некорректные параметры запроса", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc: StarletteHTTPException):
        code = _HTTP_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
        return _respond(request, exc.status_code, code, str(exc.detail))
