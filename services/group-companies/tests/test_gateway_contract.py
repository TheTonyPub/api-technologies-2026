"""Проверки Gateway → Group Companies без внешних сервисов."""
import importlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "libs" / "common")]

import httpx
import yaml

gateway = importlib.import_module("services.gateway.app.main")
groups = importlib.import_module("services.group-companies.app.main")
repository = groups.repository

HEADERS = {"Authorization": "Bearer zip-test", "X-Request-Id": "group-test"}
STAMP = datetime(2026, 11, 8, tzinfo=timezone.utc)
GROUPED = "/v1/companies/9990000001/group"
OTHER = "/v1/companies/9990000011/group"
SINGLE = "/v1/companies/9990000021/group"
UNKNOWN = "/v1/companies/9999999999/group"


def member(inn, bank_client, relation="AFFILIATE"):
    return {"inn": inn, "short_name": f"Company {inn}", "status": "ACTIVE",
            "group_relation": relation, "is_bank_client": bank_client}


class GroupGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        upstream = httpx.AsyncClient(transport=httpx.ASGITransport(app=groups.app))
        self.addAsyncCleanup(upstream.aclose)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway", headers=HEADERS,
        )
        self.addAsyncCleanup(self.client.aclose)

        for patcher in (
            patch.object(gateway.settings, "gateway_token", "zip-test"),
            patch.object(gateway.app.state, "client", upstream, create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        database = patch.object(repository.psycopg, "connect")
        connect = database.start()
        self.addCleanup(database.stop)
        self.query = connect.return_value.__enter__.return_value.execute
        self.query.side_effect = self.select

    def select(self, sql, params):
        rows = {
            "a": [member("9990000002", False, relation=None), member("9990000001", True)],
            "b": [member("9990000011", False)],
        }
        value = params[0]
        cursor = Mock()
        if "WHERE inn" in sql:
            company_groups = {"9990000001": "a", "9990000011": "b", "9990000021": None}
            group_id = company_groups.get(value)
            cursor.fetchone.return_value = (
                {"group_id": group_id, "group_name": group_id, "data_as_of": STAMP}
                if value in company_groups else None
            )
        else:
            self.assertIn("WHERE group_id", sql)
            self.assertIn("ORDER BY inn", sql)
            cursor.fetchall.return_value = sorted(rows[value], key=lambda item: item["inn"])
        return cursor

    async def test_group_members_include_requested_company_and_are_ordered(self):
        response = await self.client.get(GROUPED)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["inn"] for item in response.json()["members"]], ["9990000001", "9990000002"])
        self.assertEqual(response.json()["totalMembers"], 2)

    async def test_filter_counts_only_bank_clients(self):
        response = await self.client.get(GROUPED, params={"onlyBankClients": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["inn"] for item in response.json()["members"]], ["9990000001"])
        self.assertEqual(response.json()["totalMembers"], 1)

    async def test_unknown_group_relation_is_null(self):
        response = await self.client.get(GROUPED)
        self.assertEqual(response.status_code, 200)
        relation = response.json()["members"][1]["relation"]
        self.assertIsNone(relation)
        for service in ("api-gateway", "group-companies-service"):
            with self.subTest(contract=service):
                path = ROOT / "contracts" / service / "openapi.yaml"
                contract = yaml.safe_load(path.read_text(encoding="utf-8"))
                schema = contract["components"]["schemas"]["GroupMember"]["properties"]["relation"]
                self.assertIn("null", schema["type"])
                self.assertIn(relation, schema["enum"])

    async def test_group_without_bank_clients_and_company_without_group(self):
        filtered = await self.client.get(OTHER, params={"onlyBankClients": "true"})
        single = await self.client.get(SINGLE)
        self.assertEqual((filtered.status_code, single.status_code), (200, 200))
        for response in (filtered, single):
            self.assertEqual((response.json()["members"], response.json()["totalMembers"]), ([], 0))
        self.assertEqual(filtered.json()["groupId"], "b")
        self.assertIsNone(single.json()["groupId"])

    async def test_unknown_company_and_invalid_filter(self):
        unknown = await self.client.get(UNKNOWN)
        invalid = await self.client.get(GROUPED, params={"onlyBankClients": "bad-value"})
        self.assertEqual((unknown.status_code, unknown.json()["code"]), (404, "COMPANY_NOT_FOUND"))
        self.assertEqual((invalid.status_code, invalid.json()["code"]), (400, "INVALID_REQUEST"))
