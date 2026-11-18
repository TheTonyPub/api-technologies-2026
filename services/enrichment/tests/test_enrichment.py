"""интеграционные тесты Enrichment, нужны Postgres и Redis из compose
тестовые ИНН 997xxxxxxx, чистим до и после, АБС тут подменён
"""
import datetime as dt
import json
import os
import time

import httpx
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
from app import abs_client, cache, pipeline  # noqa: E402
from app.store import connect  # noqa: E402

import importlib.util  # scd2 лежит в другом сервисе с тем же именем пакета app
_spec = importlib.util.spec_from_file_location("scd2", os.path.join(ROOT, "loader", "app", "scd2.py"))
scd2 = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(scd2)

T0 = dt.datetime(2026, 11, 8, 6, 0, tzinfo=dt.timezone.utc)
N, CLIENTS = 100, 45


def _co(i, **over):
    d = {"inn": f"997{i:07d}", "ogrn": f"102{i:010d}", "kpp": "997001001", "short_name": f"ООО {i}",
         "full_name": f"Общество {i}", "status": "ACTIVE", "registration_date": "2012-03-15",
         "legal_address": f"г. Москва, д. {i}", "okved_code": "64.19",
         "okved_name": "Денежное посредничество прочее", "group_id": "grp-test-1" if i < 4 else None}
    d.update(over)
    return d


@pytest.fixture()
def db(monkeypatch):
    try:
        conn = connect()
        r = cache.get_redis(); r.ping()
    except Exception as e:
        if os.getenv("CI") == "true":
            raise
        pytest.skip(f"нет Postgres/Redis: {e}")

    def clean():
        with conn.cursor() as cur:
            for t in ("company_snapshot", "company_outbox", "company_versions", "bank_clients"):
                cur.execute(f"DELETE FROM {t} WHERE inn LIKE '997%'")
            cur.execute("DELETE FROM company_groups WHERE group_id='grp-test-1'")
        conn.commit()
        for k in r.scan_iter("company:997*"):
            r.delete(k)
    clean()
    scd2.upsert_group(conn, "grp-test-1", "Группа")
    for i in range(N):
        scd2.upsert_company(conn, _co(i), T0)
    clients = {f"997{i:07d}" for i in range(CLIENTS)}
    monkeypatch.setattr(abs_client, "lookup", lambda inns, client=None: {i: i in clients for i in inns})
    yield conn, r
    clean(); conn.close()


def test_rebuild_counts_and_cache(db):
    conn, r = db
    pipeline.rebuild_all(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE is_bank_client) FROM company_snapshot WHERE inn LIKE '997%'")
        assert cur.fetchone() == (N, CLIENTS)
    assert sum(1 for _ in r.scan_iter("company:997*")) == N
    key = "company:9970000000"
    assert 0 < r.ttl(key) <= cache.CACHE_TTL_SECONDS
    assert json.loads(r.get(key))["inn"] == "9970000000"


def test_rebuild_is_idempotent_and_picks_up_changes(db):
    conn, r = db
    pipeline.rebuild_all(conn); pipeline.rebuild_all(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM company_snapshot WHERE inn LIKE '997%'")
        assert cur.fetchone()[0] == N
    assert scd2.upsert_company(conn, _co(7, legal_address="г. Казань"), T0 + dt.timedelta(hours=1))
    pipeline.rebuild_all(conn)
    assert "Казань" in r.get("company:9970000007").decode()


def test_abs_failure_keeps_previous_flags(db, monkeypatch):
    conn, _ = db
    pipeline.rebuild_all(conn)
    monkeypatch.setattr(abs_client, "lookup", lambda inns, client=None: {})  # АБС лежит
    pipeline.rebuild_all(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM company_snapshot WHERE is_bank_client AND inn LIKE '997%'")
        assert cur.fetchone()[0] == CLIENTS


def test_abs_retry_on_429_then_ok(monkeypatch):
    monkeypatch.setattr(abs_client.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"clients": [{"inn": "1", "isBankClient": True}]})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert abs_client.lookup(["1", "2"], client=c) == {"1": True, "2": False}
    assert calls["n"] == 3


def test_abs_401_does_not_raise(monkeypatch):
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert abs_client.lookup(["1"], client=c) == {}


def test_abs_batches_of_500(monkeypatch):
    sizes = []
    def handler(req):
        sizes.append(len(json.loads(req.content)["inns"]))
        return httpx.Response(200, json={"clients": []})
    monkeypatch.setattr(abs_client.time, "sleep", lambda s: None)
    abs_client.lookup([str(i) for i in range(1000)], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert sizes == [500, 500]


def test_history_endpoint(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.history import router
    conn, _ = db
    scd2.upsert_company(conn, _co(7, legal_address="г. Казань"), T0 + dt.timedelta(hours=1))
    app = FastAPI(); app.include_router(router)
    cl = TestClient(app)
    body = cl.get("/v1/internal/companies/9970000007/history").json()
    assert body["versionsCount"] == 2
    assert body["versions"][1]["changedFields"] == [
        {"field": "legal_address", "old": "г. Москва, д. 7", "new": "г. Казань"}]
    assert body["versions"][0]["validTo"] and body["versions"][1]["isCurrent"] is True
    r = cl.get("/v1/internal/companies/9979999999/history")
    assert r.status_code == 404 and r.json()["code"] == "COMPANY_NOT_FOUND"


def test_service_builds_and_refreshes_snapshot(db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    conn, redis = db
    keys = ["initial_done", "last_sync_at"]
    previous = conn.execute("SELECT key, value FROM load_state WHERE key = ANY(%s)", (keys,)).fetchall()

    def set_state(key, value):
        conn.execute(
            "INSERT INTO load_state (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )
        conn.commit()

    def wait_until(condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        pytest.fail(f"Фоновая сборка не завершилась: {pipeline.state}")

    monkeypatch.setattr(pipeline, "POLL_SEC", 0.05)
    monkeypatch.setattr(pipeline, "state",
                        dict(built=False, data_as_of=None, last_error=None, synced_marker=None))
    card_key = "company:9970000007"
    try:
        set_state("initial_done", "false")
        set_state("last_sync_at", T0.isoformat())
        with TestClient(app) as client:
            response = client.get("/status")
            assert response.status_code == 200 and response.json()["ready"] is False
            assert redis.get(card_key) is None

            set_state("initial_done", "true")
            wait_until(lambda: client.get("/status").json()["ready"])
            assert client.get("/status").json()["companies"] == N
            assert json.loads(redis.get(card_key))["legalAddress"] == "г. Москва, д. 7"
            built_at = conn.execute(
                "SELECT built_at FROM company_snapshot WHERE inn = %s", ("9970000007",)
            ).fetchone()[0]

            later = T0 + dt.timedelta(hours=1)
            scd2.upsert_company(conn, _co(7, legal_address="г. Казань"), later)
            set_state("last_sync_at", later.isoformat())
            wait_until(lambda: json.loads(redis.get(card_key))["legalAddress"] == "г. Казань")
            refreshed_at = conn.execute(
                "SELECT built_at FROM company_snapshot WHERE inn = %s", ("9970000007",)
            ).fetchone()[0]
            assert refreshed_at > built_at
            assert client.get("/v1/internal/companies/9970000007/history").json()["versionsCount"] == 2
    finally:
        conn.execute("DELETE FROM load_state WHERE key = ANY(%s)", (keys,))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO load_state (key, value) VALUES (%s, %s)", previous)
        conn.commit()
