"""тесты SCD2 против Postgres из compose
запускать так: docker compose up -d postgres  &&  python scripts/dev.py test
берём DSN из TEST_DATABASE_URL или DATABASE_URL, по умолчанию localhost:5432 spark/spark/spark
тестовые ИНН начинаются с 998, чистим до и после каждого теста
"""
import datetime as dt
import os
import threading

import pytest

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


@pytest.fixture()
def conn():
    try:
        c = pg.connect(DSN)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres недоступен: {e}")
    _clean(c)
    yield c
    _clean(c)
    c.close()


def _versions(conn, inn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT valid_from, valid_to, is_current, legal_address FROM company_versions "
            "WHERE inn = %s ORDER BY valid_from, id", (inn,))
        return cur.fetchall()


def test_new_company_gives_one_version(conn):
    assert scd2.upsert_company(conn, _company(), T0) is True
    rows = _versions(conn, "9980000001")
    assert len(rows) == 1
    assert rows[0][0] == T0 and rows[0][1] is None and rows[0][2] is True


def test_same_data_adds_no_version(conn):
    scd2.upsert_company(conn, _company(), T0)
    assert scd2.upsert_company(conn, _company(), T1) is False
    assert len(_versions(conn, "9980000001")) == 1


def test_changed_address_closes_old_and_opens_new(conn):
    scd2.upsert_company(conn, _company(), T0)
    assert scd2.upsert_company(conn, _company(legal_address="г. Казань, ул. Новая, 5"), T1) is True
    old, new = _versions(conn, "9980000001")
    assert old[1] == T1 and old[2] is False          # у первой появился valid_to
    assert new[0] == T1 and new[1] is None and new[2] is True  # вторая текущая
    assert new[3] == "г. Казань, ул. Новая, 5"


def test_repeat_run_changes_nothing(conn):
    c1, c2 = _company(), _company(legal_address="г. Казань, ул. Новая, 5")
    for _ in range(3):
        scd2.upsert_company(conn, c1, T0)
    scd2.upsert_company(conn, c2, T1)
    before = _versions(conn, "9980000001")
    assert scd2.upsert_company(conn, c2, T1 + dt.timedelta(hours=1)) is False
    assert _versions(conn, "9980000001") == before


def test_hash_ignores_key_order_and_service_fields():
    a = _company()
    b = dict(reversed(list(a.items())))
    b.update(id=5, valid_from=T0, valid_to=None, is_current=True, attrs_hash="x")
    assert scd2.compute_attrs_hash(a) == scd2.compute_attrs_hash(b)
    assert scd2.compute_attrs_hash(a) != scd2.compute_attrs_hash(_company(status="LIQUIDATED"))


def test_group_change_is_new_version(conn):
    scd2.upsert_group(conn, "grp-test-1", "Группа 1")
    scd2.upsert_company(conn, _company(), T0)
    scd2.upsert_company(conn, _company(group_id="grp-test-1"), T1)
    assert len(_versions(conn, "9980000001")) == 2


def test_upsert_group_idempotent_and_renames(conn):
    assert scd2.upsert_group(conn, "grp-test-1", "A") is True
    assert scd2.upsert_group(conn, "grp-test-1", "A") is False
    assert scd2.upsert_group(conn, "grp-test-1", "B") is True
    with conn.cursor() as cur:
        cur.execute("SELECT group_name FROM company_groups WHERE group_id='grp-test-1'")
        assert cur.fetchone()[0] == "B"


def test_concurrent_upserts_same_inn_give_single_current(conn):
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
    assert not errors
    assert results.count(True) == 1
    assert len(_versions(conn, "9980000002")) == 1


def test_none_equals_missing_key_in_hash():
    a = _company()
    b = {k: v for k, v in a.items() if k not in ("group_id", "group_relation")}
    assert scd2.compute_attrs_hash(a) == scd2.compute_attrs_hash(b)
    assert scd2.compute_attrs_hash(a) != scd2.compute_attrs_hash(_company(group_id="grp-1"))


def test_revision_and_actual_date_would_break_hash_so_parser_must_not_pass_them():
    """правило такое, Revision и ActualDate из отчёта СПАРК в словарь компании не класть"""
    assert scd2.compute_attrs_hash(_company()) != scd2.compute_attrs_hash(_company(actual_date="2026-10-30 20:53:39+00:00"))
