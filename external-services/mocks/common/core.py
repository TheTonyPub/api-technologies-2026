"""Общая часть всех моков: ключи, X-Request-Id, сценарии сбоев, лимиты, формат ошибок."""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

SEED = int(os.getenv("MOCK_SEED", "2026"))


def stable_int(*parts: object) -> int:
    """Детерминированное 64-битное число из любых частей (не зависит от PYTHONHASHSEED)."""
    raw = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")


def rng_for(*parts: object) -> random.Random:
    return random.Random(stable_int(SEED, *parts))


# ---------------------------------------------------------------- ключи команд

def load_keys() -> dict[str, str]:
    """MOCK_API_KEYS="team1:key1,team2:key2" -> {key: team}."""
    raw = os.getenv("MOCK_API_KEYS", "demo:demo-key")
    keys: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        team, _, key = item.partition(":")
        keys[key.strip()] = team.strip()
    return keys


API_KEYS = load_keys()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None, details=None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details


def team_from_key(key: str | None) -> str:
    if not key or key not in API_KEYS:
        raise ApiError(401, "UNAUTHORIZED", "Нет ключа или ключ неверный: передайте заголовок X-API-Key")
    return API_KEYS[key]


def require_team(request: Request) -> str:
    """FastAPI-зависимость: команда по заголовку X-API-Key."""
    return team_from_key(request.headers.get("X-API-Key"))


# ---------------------------------------------------------------- лимиты

class RateLimiter:
    """Скользящее окно в 1 секунду на (команда, сервис)."""

    def __init__(self, per_second: int):
        self.per_second = per_second
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, who: str) -> int:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(who, []) if now - t < 1.0]
            if len(hits) >= self.per_second:
                self._hits[who] = hits
                raise ApiError(429, "RATE_LIMIT", f"Не больше {self.per_second} запросов в секунду",
                               headers={"Retry-After": "1"})
            hits.append(now)
            self._hits[who] = hits
            return self.per_second - len(hits)


# ---------------------------------------------------------------- сценарии сбоев

SCENARIOS = {"slow", "timeout", "error", "unavailable", "ratelimit"}
BG_ERROR_RATE = float(os.getenv("MOCK_BG_ERROR_RATE", "0"))
BG_LATENCY_MS = os.getenv("MOCK_BG_LATENCY_MS", "")  # например "50-300"


@dataclass
class ErrorStyle:
    """Как оформлять ошибки: у большинства моков свой формат, у /notify — как у SendGrid/FCM."""

    def render(self, request: Request, err: ApiError) -> Response:
        rid = request.state.request_id
        body = {"code": err.code, "message": err.message, "traceId": rid}
        if err.details:
            body["details"] = err.details
        return JSONResponse(body, status_code=err.status, headers=err.headers)


class MockMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, style: ErrorStyle):
        super().__init__(app)
        self.style = style

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = rid
        path = request.url.path
        service_path = not (path.endswith("/health") or path.endswith("/docs") or path.endswith("openapi.json")
                            or "/docs/" in path)
        scenario = (request.headers.get("X-Mock-Scenario") or "").strip().lower()
        try:
            if service_path:
                await self._apply_faults(scenario)
            response = await call_next(request)
        except ApiError as err:
            response = self.style.render(request, err)
        response.headers["X-Request-Id"] = rid
        return response

    async def _apply_faults(self, scenario: str):
        if BG_LATENCY_MS:
            lo, _, hi = BG_LATENCY_MS.partition("-")
            await asyncio.sleep(random.uniform(float(lo), float(hi or lo)) / 1000)
        if scenario == "slow":
            await asyncio.sleep(3)
        elif scenario == "timeout":
            await asyncio.sleep(30)
            raise ApiError(504, "UPSTREAM_TIMEOUT", "Сценарий timeout: ответ не успел за 30 секунд")
        elif scenario == "error":
            raise ApiError(500, "INTERNAL_ERROR", "Сценарий error: внутренняя ошибка")
        elif scenario == "unavailable":
            raise ApiError(503, "SERVICE_UNAVAILABLE", "Сценарий unavailable: сервис недоступен",
                           headers={"Retry-After": "5"})
        elif scenario == "ratelimit":
            raise ApiError(429, "RATE_LIMIT", "Сценарий ratelimit: слишком много запросов",
                           headers={"Retry-After": "1"})
        if BG_ERROR_RATE and random.random() < BG_ERROR_RATE:
            raise ApiError(503, "SERVICE_UNAVAILABLE", "Временная недоступность (фоновый сбой)",
                           headers={"Retry-After": "2"})


SCENARIO_DOC = (
    "\n\n**Общее для всех моков.** Ключ команды в `X-API-Key`. Заголовок `X-Request-Id` можно передать, "
    "он вернётся в ответе. Сбои по запросу: `X-Mock-Scenario: slow | timeout | error | unavailable | ratelimit`. "
    "Данные вымышленные и генерируются детерминированно: у всех одинаковые."
)


def create_app(title: str, description: str, version: str = "1.0.0", style: ErrorStyle | None = None,
               tags: list[dict] | None = None) -> FastAPI:
    root_path = os.getenv("ROOT_PATH", "")
    app = FastAPI(title=title, description=description + SCENARIO_DOC, version=version,
                  root_path=root_path, openapi_tags=tags)
    style = style or ErrorStyle()
    app.add_middleware(MockMiddleware, style=style)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, err: ApiError):
        return style.render(request, err)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, err: HTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(err.status_code, "HTTP_ERROR")
        return style.render(request, ApiError(err.status_code, code, str(err.detail)))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, err: RequestValidationError):
        details = [{"field": ".".join(str(x) for x in e["loc"][1:]) or str(e["loc"][0]), "problem": e["msg"]}
                   for e in err.errors()]
        return style.render(request, ApiError(400, "INVALID_REQUEST", "Неверные параметры запроса",
                                              details=details))

    @app.get("/health", tags=["service"], summary="Проверка, что мок жив (без ключа)")
    async def health():
        return {"status": "ok"}

    return app


def page(items: list, next_cursor: str | None) -> dict:
    return {"items": items, "nextCursor": next_cursor}
