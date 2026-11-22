"""Клиент для внешних API (АБС и бюро данных).

Что он умеет:
- кладёт X-API-Key (и X-Mock-Scenario, если задан MOCK_SCENARIO);
- не отправляет больше MAX_RPS запросов в секунду;
- на каждый запрос ставит таймаут;
- при 429, 503 (и других 5xx) и таймаутах ждёт и повторяет, учитывает Retry-After;
- 401 и 404 не повторяет, а кидает ApiError, и вызывающий код сам решает, что делать.
"""
import logging
import time

import requests

import config

log = logging.getLogger("http")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class ApiClient:
    def __init__(self, service):
        # service: "abs" или "client-data", это начало пути на сервере моков
        self.base = f"{config.BASE_URL}/{service}"
        self.min_interval = 1.0 / config.MAX_RPS
        self.last_call = 0.0
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = config.API_KEY
        if config.MOCK_SCENARIO:
            self.session.headers["X-Mock-Scenario"] = config.MOCK_SCENARIO

    def _wait_turn(self):
        # между двумя запросами должно пройти не меньше min_interval секунд
        pause = self.last_call + self.min_interval - time.time()
        if pause > 0:
            time.sleep(pause)
        self.last_call = time.time()

    def request(self, method, path, **kwargs):
        url = self.base + path
        last_status = 0
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._wait_turn()
            try:
                resp = self.session.request(method, url, timeout=config.REQUEST_TIMEOUT, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as e:
                log.warning("%s %s: сеть/таймаут (%s), попытка %d", method, path, type(e).__name__, attempt)
                time.sleep(self._backoff(attempt))
                continue

            if resp.status_code < 400:
                return resp.json()

            last_status = resp.status_code
            request_id = resp.headers.get("X-Request-Id")
            if resp.status_code in (429, 500, 502, 503, 504):
                # временная ошибка: ждём и пробуем ещё раз
                delay = self._retry_after(resp, attempt)
                log.warning("%s %s: %d (request_id=%s), жду %.1f с, попытка %d",
                            method, path, resp.status_code, request_id, delay, attempt)
                time.sleep(delay)
                continue

            # 401, 404, 400 и т.п.: повторять бесполезно
            raise ApiError(resp.status_code, resp.text[:200])

        raise ApiError(last_status, f"{method} {path}: кончились попытки")

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body):
        return self.request("POST", path, json=body)

    @staticmethod
    def _backoff(attempt):
        # 1, 2, 4, 8 ... секунд, но не больше 30
        return min(2 ** (attempt - 1), 30)

    def _retry_after(self, resp, attempt):
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), 30)
            except ValueError:
                pass
        return self._backoff(attempt)
