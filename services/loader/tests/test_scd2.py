"""тесты SCD2 против Postgres из compose
запускать так: docker compose up -d postgres  &&  python scripts/dev.py test
берём DSN из TEST_DATABASE_URL или DATABASE_URL, по умолчанию localhost:5432 spark/spark/spark
тестовые ИНН начинаются с 998, чистим до и после каждого теста
"""
import datetime as dt
import os
import threading
import unittest

try:
    import psycopg as pg
except ImportError:  # pragma: no cover
    import psycopg2 as pg

from app import scd2

DSN = (
    os.getenv("TEST_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql://spark:spark@localhost:5432/spark"
)
T0 = dt.datetime(2026, 11, 8, 6, 0, tzinfo=dt.timezone.utc)
T1 = T0 + dt.timedelta(hours=1)


def _company(inn="9980000001", **over):
    base = {
        "inn": inn, "ogrn": "1029980000001", "kpp": "997001001",
        "short_name": "ООО «Тест»", "full_name": "Общество «Тест»",
        "status": "ACTIVE", "registration_date": "2012-03-15",
        "legal_address": "г. Москва, ул. Тестовая, д. 1",
        "okved_code": "64.19", "okved_name": "Денежное посредничество прочее",
        "director": "Попов Дмитрий Иванович", "group_id": None, "group_relation": None,
    }
    base.update(over)
    return base


def _clean(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM company_versions WHERE inn LIKE '998%'")
        cur.execute("DELETE FROM company_groups WHERE group_id LIKE 'grp-test-%'")
    conn.commit()


def _versions(conn, inn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT valid_from, valid_to, is_current, legal_address FROM company_versions "
            "WHERE inn = %s ORDER BY valid_from, id", (inn,))
        return cur.fetchall()


class Scd2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            c = pg.connect(DSN)
            c.close()
            cls.pg_available = True
        except Exception as e:
            cls.pg_available = False
            cls.pg_error = e

    def setUp(self):
        if not self.pg_available:
            self.skipTest(f"Postgres недоступен: {self.pg_error}")
        self.conn = pg.connect(DSN)
        _clean(self.conn)

    def tearDown(self):
        if hasattr(self, "conn") and self.conn is not None:
            try:
                _clean(self.conn)
            finally:
                self.conn.close()

    def test_new_company_gives_one_version(self):
        conn = self.conn
        self.assertTrue(scd2.upsert_company(conn, _company(), T0))
        rows = _versions(conn, "9980000001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], T0)
        self.assertIsNone(rows[0][1])
        self.assertTrue(rows[0][2])

    def test_same_data_adds_no_version(self):
        conn = self.conn
        scd2.upsert_company(conn, _company(), T0)
        self.assertFalse(scd2.upsert_company(conn, _company(), T1))
        self.assertEqual(len(_versions(conn, "9980000001")), 1)

    def test_changed_address_closes_old_and_opens_new(self):
        conn = self.conn
        scd2.upsert_company(conn, _company(), T0)
        self.assertTrue(
            scd2.upsert_company(conn, _company(legal_address="г. Казань, ул. Новая, 5"), T1)
        )
        old, new = _versions(conn, "9980000001")
        self.assertEqual(old[1], T1)
        self.assertFalse(old[2])  # у первой появился valid_to
        self.assertEqual(new[0], T1)
        self.assertIsNone(new[1])
        self.assertTrue(new[2])  # вторая текущая
        self.assertEqual(new[3], "г. Казань, ул. Новая, 5")

    def test_repeat_run_changes_nothing(self):
        conn = self.conn
        c1, c2 = _company(), _company(legal_address="г. Казань, ул. Новая, 5")
        for _ in range(3):
            scd2.upsert_company(conn, c1, T0)
        scd2.upsert_company(conn, c2, T1)
        before = _versions(conn, "9980000001")
        self.assertFalse(scd2.upsert_company(conn, c2, T1 + dt.timedelta(hours=1)))
        self.assertEqual(_versions(conn, "9980000001"), before)

    def test_hash_ignores_key_order_and_service_fields(self):
        a = _company()
        b = dict(reversed(list(a.items())))
        b.update(id=5, valid_from=T0, valid_to=None, is_current=True, attrs_hash="x")
        self.assertEqual(scd2.compute_attrs_hash(a), scd2.compute_attrs_hash(b))
        self.assertNotEqual(
            scd2.compute_attrs_hash(a),
            scd2.compute_attrs_hash(_company(status="LIQUIDATED")),
        )

    def test_group_change_is_new_version(self):
        conn = self.conn
        scd2.upsert_group(conn, "grp-test-1", "Группа 1")
        scd2.upsert_company(conn, _company(), T0)
        scd2.upsert_company(conn, _company(group_id="grp-test-1"), T1)
        self.assertEqual(len(_versions(conn, "9980000001")), 2)

    def test_upsert_group_idempotent_and_renames(self):
        conn = self.conn
        self.assertTrue(scd2.upsert_group(conn, "grp-test-1", "A"))
        self.assertFalse(scd2.upsert_group(conn, "grp-test-1", "A"))
        self.assertTrue(scd2.upsert_group(conn, "grp-test-1", "B"))
        with conn.cursor() as cur:
            cur.execute("SELECT group_name FROM company_groups WHERE group_id='grp-test-1'")
            self.assertEqual(cur.fetchone()[0], "B")

    def test_concurrent_upserts_same_inn_give_single_current(self):
        conn = self.conn
        results, errors = [], []

        def worker():
            c = pg.connect(DSN)
            try:
                results.append(scd2.upsert_company(c, _company(inn="9980000002"), T0))
            except Exception as e:  # noqa
                errors.append(e)
            finally:
                c.close()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertFalse(errors)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(_versions(conn, "9980000002")), 1)

    def test_none_equals_missing_key_in_hash(self):
        a = _company()
        b = {k: v for k, v in a.items() if k not in ("group_id", "group_relation")}
        self.assertEqual(scd2.compute_attrs_hash(a), scd2.compute_attrs_hash(b))
        self.assertNotEqual(
            scd2.compute_attrs_hash(a),
            scd2.compute_attrs_hash(_company(group_id="grp-1")),
        )

    def test_revision_and_actual_date_would_break_hash_so_parser_must_not_pass_them(self):
        """правило такое, Revision и ActualDate из отчёта СПАРК в словарь компании не класть"""
        self.assertNotEqual(
            scd2.compute_attrs_hash(_company()),
            scd2.compute_attrs_hash(_company(actual_date="2026-10-30 20:53:39+00:00")),
        )


if __name__ == "__main__":
    unittest.main()
