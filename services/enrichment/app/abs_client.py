"""Пакетный клиент АБС для POST /v1/legal-clients:lookup."""
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
base_override = os.getenv("ABS_BASE_URL")
ABS_URL = f"{base_override.rstrip('/')}/abs" if base_override else config.settings.abs_url.rstrip("/")
LOOKUP_URL = f"{ABS_URL}/v1/legal-clients:lookup"

_FLAG_KEYS = ("is_bank_client", "isBankClient", "isClient", "bankClient", "found", "exists", "client")
_LIST_KEYS = ("items", "clients", "results", "data", "legalClients")


def build_payload(inns: list[str]) -> dict:
    return {"inns": inns}


def parse_response(body, requested: list[str]) -> dict[str, bool]:
    """Прочитать флаги из пакетного ответа АБС и совместимых моков."""
    if isinstance(body, dict) and "items" in body:
        items = body["items"]
        if not isinstance(items, list):
            raise ValueError("АБС вернул некорректный список")
        requested_inns = set(requested)
        result = {}
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get("inn"), str)
                    or not isinstance(item.get("is_bank_client"), bool)):
                raise ValueError("АБС вернул некорректный флаг клиента")
            if item["inn"] in requested_inns:
                result[item["inn"]] = item["is_bank_client"]
        return result

    items = body
    if isinstance(body, dict):
        items = next((body[k] for k in _LIST_KEYS if isinstance(body.get(k), list)), None)
    if not isinstance(items, list):
        raise ValueError("АБС вернул некорректный список")
    result = {inn: False for inn in requested}
    for it in items:
        if isinstance(it, str):
            inn, flag = it, True
        elif isinstance(it, dict) and it.get("inn") is not None:
            inn = str(it.get("inn", ""))
            flag = next((it[k] for k in _FLAG_KEYS if k in it), True)
            if not isinstance(flag, bool):
                raise ValueError("АБС вернул не булев флаг клиента")
        else:
            raise ValueError("АБС вернул запись без ИНН")
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
                LOOKUP_URL, json=build_payload(inns),
                headers=config.abs_headers(), timeout=TIMEOUT_SEC,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            log.warning("АБС: %s (попытка %d/%d)", type(e).__name__, attempt, MAX_ATTEMPTS)
            time.sleep(pause)
            continue
        if resp.status_code == 200:
            try:
                return parse_response(resp.json(), inns)
            except ValueError:
                log.warning("АБС вернул некорректный ответ. Пачка пропущена.")
                return None
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
