"""гоняем цепочку АБС, потом bank_clients, потом company_snapshot, потом Redis

run_forever() запускается в фоновом потоке из main.py
сначала ждём пока load_state.initial_done станет true, потом собираем срез и кэш
дальше каждые ENRICH_POLL_SEC сек смотрим load_state.last_sync_at, изменился значит пересобираем всё
любая ошибка поток не убивает, просто пауза с нарастанием и повтор
"""
import datetime as dt
import logging
import os
import threading

from . import abs_client, cache, snapshot
from .store import connect

log = logging.getLogger("enrichment.pipeline")
POLL_SEC = float(os.getenv("ENRICH_POLL_SEC", "5"))

state = {"built": False, "data_as_of": None, "last_error": None, "synced_marker": None}
_lock = threading.Lock()


def _load_state(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM load_state WHERE key = %s", (key,))
        row = cur.fetchone()
    return None if row is None else row[0]


def _is_true(v) -> bool:
    # value может лежать как 'true', 'True', '1' или JSON true
    return str(v).strip().lower() in ("true", "1", "t", "yes")


def refresh_bank_clients(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT inn FROM company_versions WHERE is_current")
        inns = [r[0] for r in cur.fetchall()]
    found = abs_client.lookup(inns)  # только успешно полученные пачки
    if not found:
        log.warning("АБС не дал данных: bank_clients остаётся прежним")
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bank_clients (inn, is_bank_client, checked_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (inn) DO UPDATE SET is_bank_client = EXCLUDED.is_bank_client, "
            "checked_at = EXCLUDED.checked_at",
            [(inn, flag, dt.datetime.now(dt.timezone.utc)) for inn, flag in found.items()],
        )
    conn.commit()
    log.info("bank_clients: обновлено %d записей, клиентов банка %d", len(found), sum(found.values()))
    return len(found)


def rebuild_all(conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    try:
        started = dt.datetime.now(dt.timezone.utc)
        refresh_bank_clients(conn)
        rows = snapshot.rebuild_snapshot(conn, started)  # data_as_of это время сборки
        cards = cache.publish_cards(conn)
        with _lock:
            state.update(built=True, data_as_of=started, last_error=None)
        return {"snapshot_rows": rows, "cards": cards}
    finally:
        if own:
            conn.close()


def run_forever(stop: threading.Event | None = None):
    stop = stop or threading.Event()
    backoff = 2.0
    while not stop.is_set():
        try:
            conn = connect()
            try:
                if _is_true(_load_state(conn, "initial_done")):
                    marker = _load_state(conn, "last_sync_at")
                    if not state["built"] or marker != state["synced_marker"]:
                        log.info("Пересборка среза (last_sync_at=%s)", marker)
                        rebuild_all(conn)
                        state["synced_marker"] = marker
                backoff = 2.0
            finally:
                conn.close()
            stop.wait(POLL_SEC)
        except Exception as e:  # noqa: BLE001 - поток не должен умирать
            state["last_error"] = repr(e)
            log.exception("Enrichment: ошибка, повтор через %.0f c", backoff)
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)
