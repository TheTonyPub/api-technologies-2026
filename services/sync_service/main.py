"""Сервис синхронизации данных.

При старте загружает всё нужное из АБС и бюро, потом по таймеру обновляет.
Ещё в нём есть маленький HTTP-сервер: /health (жив ли) и /stats (сколько чего загружено).
"""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

import config
import db
import loaders
from http_client import ApiClient, ApiError

log = logging.getLogger("main")


def run_job(name, func):
    """Запускает одну загрузку. Любая ошибка только пишется в лог, сервис не падает."""
    started = time.time()
    conn = None
    try:
        conn = db.connect()  # на каждую загрузку своё подключение: если Postgres перезапустили, это не страшно
        func(conn)
        log.info("[%s] готово за %.1f с", name, time.time() - started)
        return True
    except ApiError as e:
        if e.status == 401:
            log.error("[%s] 401: проверьте API_KEY в .env", name)
        else:
            log.error("[%s] ошибка внешнего API: %s", name, e)
    except Exception:
        log.exception("[%s] ошибка", name)
    finally:
        if conn is not None:
            conn.close()
    return False


def make_http_handler(redis_client):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"status": "ok"})
            elif self.path == "/stats":
                try:
                    self.send_json(200, collect_stats(redis_client))
                except Exception as e:
                    self.send_json(500, {"error": str(e)})
            else:
                self.send_json(404, {"error": "not found"})

        def send_json(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # не пишем каждый запрос в лог

    return Handler


def collect_stats(redis_client):
    conn = db.connect()
    try:
        stats = db.get_counts(conn)
        initial = db.get_state(conn, "initial_tx_count")
        stats["initial_tx_count"] = int(initial) if initial else None  # сколько операций было после первой загрузки
        stats["tx_loaded_until"] = db.get_state(conn, "tx_loaded_until")
    finally:
        conn.close()
    stats["redis_regions"] = redis_client.hlen(loaders.REDIS_REGION_KEY)
    stats["redis_merchants"] = redis_client.hlen(loaders.REDIS_MERCHANT_KEY)
    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.API_KEY:
        log.warning("API_KEY пустой, внешние API ответят 401")
    if config.MOCK_SCENARIO:
        log.info("включён сценарий сбоев моков: %s", config.MOCK_SCENARIO)

    conn = db.connect()
    db.init_schema(conn)
    conn.close()

    redis_client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
    abs_api = ApiClient("abs")
    bureau_api = ApiClient("client-data")

    server = ThreadingHTTPServer(("0.0.0.0", config.HTTP_PORT), make_http_handler(redis_client))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # (название, что вызвать, как часто обновлять в секундах). Порядок важен: сначала клиенты.
    jobs = [
        ("clients", lambda conn: loaders.load_clients_and_accounts(abs_api, conn), config.CLIENTS_EVERY),
        ("transactions", lambda conn: loaders.load_transactions(abs_api, conn), config.TX_EVERY),
        ("profiles", lambda conn: loaders.load_profiles(bureau_api, conn), config.PROFILES_EVERY),
        ("risks", lambda conn: loaders.load_risks(bureau_api, redis_client), config.RISKS_EVERY),
    ]
    next_run = {name: 0 for name, _, _ in jobs}  # 0 значит "запустить сразу при старте"

    while True:
        for name, func, every in jobs:
            if time.time() >= next_run[name]:
                ok = run_job(name, func)
                # если загрузка упала, пробуем снова через минуту, а не через час
                next_run[name] = time.time() + (every if ok else config.RETRY_FAILED_AFTER)
        time.sleep(5)


if __name__ == "__main__":
    main()
