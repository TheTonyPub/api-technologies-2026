"""Проверки Gateway → Client Info без внешних сервисов."""
import importlib
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "libs" / "common")]

import httpx
from redis.exceptions import ConnectionError as RedisConnectionError

gateway = importlib.import_module("services.gateway.app.main")
client_info = importlib.import_module("services.client-info.app.main")
repository = client_info.repository

INN = "9990000001"
PATH = f"/v1/companies/{INN}"
HEADERS = {"Authorization": "Bearer zip-test", "X-Request-Id": "card-test"}
ROW = {
    "inn": INN,
    "ogrn": "1029990000001",
    "short_name": "Test Company",
    "status": "ACTIVE",
    "registration_date": date(2012, 3, 15),
    "legal_address": "Test address",
    "okved_code": "64.19",
    "okved_name": "Test activity",
    "is_bank_client": True,
    "data_as_of": datetime(2026, 11, 8, tzinfo=timezone.utc),
}


class ClientInfoGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        upstream = httpx.AsyncClient(transport=httpx.ASGITransport(app=client_info.app))
        self.addAsyncCleanup(upstream.aclose)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway",
        )
        self.addAsyncCleanup(self.client.aclose)

        for patcher in (
            patch.object(gateway.settings, "gateway_token", "zip-test"),
            patch.object(gateway.app.state, "client", upstream, create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        database = patch.object(repository.psycopg, "connect")
        self.connect = database.start()
        self.addCleanup(database.stop)
        self.query = self.connect.return_value.__enter__.return_value.execute
        self.query.return_value.fetchone.return_value = ROW

        redis = patch.object(repository, "cache")
        self.cache = redis.start()
        self.addCleanup(redis.stop)
        stored = {}
        self.cache.get.side_effect = stored.get

        def set_card(key, value, *, ex, nx):
            self.assertGreater(ex, 0)
            self.assertTrue(nx)
            stored.setdefault(key, value)

        self.cache.set.side_effect = set_card

    async def test_card_cache_miss_then_hit_through_gateway(self):
        with self.assertLogs("uvicorn.error.platform", level="INFO") as access:
            first = await self.client.get(PATH, headers=HEADERS)
        second = await self.client.get(PATH, headers=HEADERS)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual((first.headers["X-Cache"], second.headers["X-Cache"]), ("MISS", "HIT"))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["inn"], INN)
        self.assertEqual(second.headers["X-Request-Id"], "card-test")
        for service in ("API Gateway", "Client Info Service"):
            self.assertTrue(any(service in line and "X-Request-Id='card-test'" in line
                                for line in access.output), access.output)
        self.connect.assert_called_once()

    async def test_redis_failure_uses_postgresql(self):
        self.cache.get.side_effect = RedisConnectionError("offline")
        self.cache.set.side_effect = RedisConnectionError("offline")
        response = await self.client.get(PATH, headers=HEADERS)
        self.assertEqual((response.status_code, response.headers["X-Cache"]), (200, "MISS"))
        self.assertEqual(response.json()["inn"], INN)
        self.connect.assert_called_once()

    async def test_unknown_company_preserves_trace(self):
        self.query.return_value.fetchone.return_value = None
        response = await self.client.get(PATH, headers=HEADERS)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "COMPANY_NOT_FOUND")
        self.assertEqual(response.headers["X-Request-Id"], response.json()["traceId"])
        self.assertEqual(response.json()["traceId"], "card-test")

    async def test_invalid_inn_and_missing_token(self):
        response = await self.client.get("/v1/companies/123", headers=HEADERS)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "INVALID_REQUEST"))
        response = await self.client.get(PATH, headers={"X-Request-Id": "card-test"})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "UNAUTHORIZED"))
        self.connect.assert_not_called()
