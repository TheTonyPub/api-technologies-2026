"""клиент АБС, POST /abs/v1/legal-clients:lookup, пачки до 500 ИНН

todo: сверить с https://api.external-services.dataprosvet.ru/abs/docs
формат запроса и ответа в ТЗ не описан, пока тут догадки (лежат в двух функциях, build_payload и parse_response)
проверка простая, после сборки в company_snapshot должно быть ровно 451 клиент банка из 1000
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from . import config

log = logging.getLogger("enrichment.abs")

BATCH_SIZE = 500
MAX_ATTEMPTS = int(os.getenv("ABS_MAX_ATTEMPTS", "6"))
TIMEOUT_SEC = float(os.getenv("ABS_TIMEOUT_SEC", "10"))
MIN_INTERVAL = 1 / 20  # лимит АБС 20 rps на команду
BASE_URL = os.getenv("ABS_BASE_URL", "https://api.external-services.dataprosvet.ru").rstrip("/")
LOOKUP_PATH = "/abs/v1/legal-clients:lookup"

_FLAG_KEYS = ("isBankClient", "isClient", "bankClient", "client", "found", "exists")
_LIST_KEYS = ("clients", "results", "items", "data", "legalClients")


def build_payload(inns: list[str]) -> dict:
    return {"inns": inns}  # пока догадка


def parse_response(body, requested: list[str]) -> dict[str, bool]:
    """отдаём {inn: is_client} по всем requested
    если булева флага нет, считаем что в ответе перечислены только клиенты (остальные False)
    todo: сверить с /abs/docs"""
    items = body
    if isinstance(body, dict):
        items = next((body[k] for k in _LIST_KEYS if isinstance(body.get(k), list)), [])
    result = {inn: False for inn in requested}
    for it in items:
        if isinstance(it, str):
            inn, flag = it, True
        else:
            inn = str(it.get("inn", ""))
            flag = next((bool(it[k]) for k in _FLAG_KEYS if k in it), True)
        if inn in result:
            result[inn] = flag
    return result


def _retry_after(resp: httpx.Response, fallback: float) -> float:
    try:
        return max(float(resp.headers.get("Retry-After", "")), 0.0)
    except ValueError:
        return fallback


def _post_batch(client: httpx.Client, inns: list[str]) -> dict[str, bool] | None:
    """если пачку получить не удалось, вернём None (сервис не падает, старые значения не трогаем)"""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        pause = min(2 ** attempt * 0.5, 30)
        try:
            resp = client.post(
                BASE_URL + LOOKUP_PATH, json=build_payload(inns),
                headers=config.abs_headers(), timeout=TIMEOUT_SEC,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            log.warning("АБС: %s (попытка %d/%d)", type(e).__name__, attempt, MAX_ATTEMPTS)
            time.sleep(pause)
            continue
        if resp.status_code == 200:
            return parse_response(resp.json(), inns)
        if resp.status_code in (429, 503):
            wait = _retry_after(resp, pause)
            log.warning("АБС %s, жду %.1f c (попытка %d/%d)", resp.status_code, wait, attempt, MAX_ATTEMPTS)
            time.sleep(wait)
            continue
        if resp.status_code in (401, 404):
            log.error("АБС %s: проверьте ABS_API_KEY / путь. Пачка пропущена.", resp.status_code)
            return None
        log.error("АБС неожиданный статус %s: %.200s", resp.status_code, resp.text)
        return None
    log.error("АБС: исчерпаны попытки, пачка из %d ИНН пропущена", len(inns))
    return None


def lookup(inns: list[str], client: httpx.Client | None = None) -> dict[str, bool]:
    """только успешно полученные пачки, провалившиеся ИНН в результат не попадают"""
    inns = sorted(set(inns))
    out: dict[str, bool] = {}
    own = client is None
    client = client or httpx.Client()
    try:
        for i in range(0, len(inns), BATCH_SIZE):
            started = time.monotonic()
            part = _post_batch(client, inns[i:i + BATCH_SIZE])
            if part is not None:
                out.update(part)
            time.sleep(max(MIN_INTERVAL - (time.monotonic() - started), 0))
    finally:
        if own:
            client.close()
    return out
