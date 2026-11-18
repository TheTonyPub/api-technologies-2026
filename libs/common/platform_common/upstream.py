"""Вызов нижестоящего REST-сервиса из Gateway: таймаут, X-Request-Id, перевод сбоев в наши ошибки."""
import httpx

from .errors import ApiError


async def get_json(client: httpx.AsyncClient, url: str, request_id: str,
                   params: dict | None = None, timeout: float = 0.9):
    try:
        r = await client.get(url, params=params, headers={"X-Request-Id": request_id}, timeout=timeout)
    except httpx.TimeoutException:
        raise ApiError(504, "UPSTREAM_TIMEOUT", "Нижестоящий сервис не ответил вовремя") from None
    except httpx.HTTPError:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Нижестоящий сервис недоступен") from None

    if r.status_code == 200:
        try:
            doc = r.json()
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            return doc, r.headers.get("X-Cache")
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Нижестоящий сервис вернул некорректный JSON")

    body = None
    try:
        body = r.json()
    except ValueError:
        pass
    if isinstance(body, dict) and "code" in body and "message" in body:
        # ошибка уже в нашем формате (404 COMPANY_NOT_FOUND и т.п.) — пробрасываем как есть
        raise ApiError(r.status_code, body["code"], body["message"], body.get("details"))
    raise ApiError(503, "SERVICE_UNAVAILABLE", f"Нижестоящий сервис вернул {r.status_code}")
