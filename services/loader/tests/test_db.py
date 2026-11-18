"""Проверки PgStore на PostgreSQL при заданном LOADER_TEST_DATABASE_URL."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from _stubs import install_env


TEST_DATABASE_URL = os.getenv("LOADER_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "LOADER_TEST_DATABASE_URL is not set")
class PgStoreTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        install_env()
        from app import db
        from app.store import PgStore

        schema = sql.Identifier(f"loader_test_{uuid4().hex}")
        admin = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        self.addCleanup(admin.close)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        self.addCleanup(admin.execute, sql.SQL("DROP SCHEMA {} CASCADE").format(schema))
        url = make_conninfo(TEST_DATABASE_URL, options=f"-csearch_path={schema.as_string()}")
        settings = patch.object(db.settings, "database_url", url)
        settings.start()
        self.addCleanup(settings.stop)

        self.db, self.store = db, PgStore()
        root = Path(__file__).resolve().parents[3]
        with db.connect() as conn:
            for migration in sorted((root / "db/migrations").glob("*.sql")):
                conn.execute(migration.read_text(encoding="utf-8"))

    def test_current_inns_excludes_closed_versions(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO company_versions(inn, attrs_hash, valid_from, valid_to, is_current) "
                "VALUES ('1', 'hash', now(), now(), false), ('2', 'hash', now(), NULL, true)"
            )
        self.assertEqual(self.store.current_inns(), {"2"})

    def test_company_failure_rolls_back_group(self):
        from psycopg.errors import UndefinedColumn

        now = datetime.now(timezone.utc)
        company = {"inn": "9980000001", "group_id": "rollback-test"}
        self.assertTrue(self.store.save(company, "Original group", now))
        with self.assertRaises(UndefinedColumn):
            self.store.save({**company, "invalid_column": "x"}, "Changed group", now)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT group_name FROM company_groups").fetchone(),
                             ("Original group",))
        self.assertEqual(self.store.counts(), {"companies": 1, "versions": 1, "groups": 1})

    def test_only_company_change_enqueues_one_event(self):
        now = datetime.now(timezone.utc)
        company = {"inn": "9980000001", "short_name": "Original"}
        updated = {**company, "short_name": "Updated"}
        self.assertTrue(self.store.save(company, None, now))
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM company_outbox").fetchone(), (0,))

        self.assertTrue(self.store.save(updated, None, now))
        self.assertFalse(self.store.save(updated, None, now))
        with self.db.connect() as conn:
            events = conn.execute(
                "SELECT o.inn, o.event_id, o.published_at, v.is_current, v.short_name "
                "FROM company_outbox o JOIN company_versions v ON v.id = o.version_id"
            ).fetchall()
        (inn, event_id, published_at, current, name), = events
        self.assertEqual((inn, published_at, current, name), (company["inn"], None, True, "Updated"))
        self.assertIsNotNone(event_id)

    def test_outbox_failure_rolls_back_new_version(self):
        from psycopg.errors import CheckViolation

        now = datetime.now(timezone.utc)
        company = {"inn": "9980000001", "short_name": "Original"}
        self.assertTrue(self.store.save(company, None, now))
        with self.db.connect() as conn:
            conn.execute("ALTER TABLE company_outbox ADD CHECK (false)")
        with self.assertRaises(CheckViolation):
            self.store.save({**company, "short_name": "Updated"}, None, now)
        with self.db.connect() as conn:
            versions = conn.execute("SELECT short_name, is_current, valid_to FROM company_versions").fetchall()
            self.assertEqual(versions, [("Original", True, None)])
            self.assertEqual(conn.execute("SELECT count(*) FROM company_outbox").fetchone(), (0,))

    def test_changed_inns_merges_existing_json_with_limit(self):
        self.store.add_changed_inns([])
        self.assertIsNone(self.store.get_state("changed_inns"))
        self.store.set_state("changed_inns", json.dumps([str(i) for i in range(100)]))
        self.store.add_changed_inns(["new", "1", "new"])
        self.assertEqual(json.loads(self.store.get_state("changed_inns")),
                         ["new", "1", "0", *[str(i) for i in range(2, 99)]])

    def test_concurrent_first_writes_preserve_all_changes(self):
        inns = [str(i) for i in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.store.add_changed_inns, ([inn] for inn in inns)))
        self.assertCountEqual(json.loads(self.store.get_state("changed_inns")), inns)
