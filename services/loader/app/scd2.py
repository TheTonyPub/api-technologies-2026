"""хранилище SCD2, версии компаний в company_versions и справочник групп

контракт для Loader (Данияр)
upsert_group(conn, group_id, group_name) возвращает bool, вызывать до upsert_company
upsert_company(conn, company, now) возвращает bool, True значит создали новую версию

company это словарь, ключи как колонки company_versions (без служебных id, valid_from, valid_to, is_current, attrs_hash, их ставит эта функция)
now это время начала загрузки, одно и то же на весь прогон (см. docs)

По умолчанию каждая функция завершает транзакцию сама. С commit=False транзакцией управляет вызывающий код.
"""
from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import json
import logging
import re

log = logging.getLogger("scd2")

# в хэш не кладём id, valid_from, valid_to, is_current и сам attrs_hash (так и написано в ТЗ)
# isBankClient сюда не попадает просто потому что его нет в company_versions
SERVICE_COLUMNS = frozenset({"id", "valid_from", "valid_to", "is_current", "attrs_hash"})

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _json_default(value):
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Нельзя сериализовать {type(value)!r} в хэш SCD2")


def business_attrs(company: dict) -> dict:
    return {k: v for k, v in company.items() if k not in SERVICE_COLUMNS}


def _hashable_attrs(company: dict) -> dict:
    # None считаем как будто ключа нет. то есть если парсер один раз отдаст
    # group_id=None, а в другой раз ключ вообще не положит, версию из-за этого не плодим
    return {k: v for k, v in business_attrs(company).items() if v is not None}


def compute_attrs_hash(company: dict) -> str:
    """sha256 от JSON бизнес-атрибутов, ключи отсортированы, служебные поля убраны"""
    payload = json.dumps(
        _hashable_attrs(company),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _db_value(value):
    # dict и list пишем JSON-строкой (Postgres сам приведёт к jsonb, если колонка jsonb)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    return value


class _Tx:
    """одна транзакция, неважно включён autocommit и какой драйвер"""

    def __init__(self, conn, commit):
        self.conn = conn
        self.commit = commit
        self.autocommit = bool(getattr(conn, "autocommit", False))

    def __enter__(self):
        if not self.commit and self.autocommit:
            raise ValueError("commit=False требует соединения без autocommit")
        self.cur = self.conn.cursor()
        if self.autocommit:
            self.cur.execute("BEGIN")
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if not self.commit:
                return False
            if exc_type is None:
                if self.autocommit:
                    self.cur.execute("COMMIT")
                else:
                    self.conn.commit()
            else:
                if self.autocommit:
                    self.cur.execute("ROLLBACK")
                else:
                    self.conn.rollback()
        finally:
            self.cur.close()
        return False


def upsert_company(conn, company: dict, now, *, commit: bool = True) -> bool:
    inn = company.get("inn")
    if not inn:
        raise ValueError("company['inn'] обязателен")
    columns = list(business_attrs(company).keys())
    for col in columns:
        if not _IDENT.match(col):
            raise ValueError(f"Недопустимое имя колонки: {col!r}")

    new_hash = compute_attrs_hash(company)

    with _Tx(conn, commit) as cur:
        # FOR UPDATE по строке, которой ещё нет, ничего не блокирует. то есть
        # работу по одному ИНН держим advisory-замком (живёт до конца транзакции)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (inn,))

        cur.execute(
            "SELECT id, attrs_hash FROM company_versions "
            "WHERE inn = %s AND is_current FOR UPDATE",
            (inn,),
        )
        current = cur.fetchone()

        if current is not None and current[1] == new_hash:
            return False  # ничего не изменилось

        if current is not None:
            # сначала закрываем старую, потом вставляем новую (иначе ux_company_current)
            cur.execute(
                "UPDATE company_versions SET valid_to = %s, is_current = false WHERE id = %s",
                (now, current[0]),
            )

        cols_sql = ", ".join(f'"{c}"' for c in columns + ["attrs_hash", "valid_from", "is_current"])
        marks = ", ".join(["%s"] * (len(columns) + 3))
        values = [_db_value(company[c]) for c in columns] + [new_hash, now, True]
        cur.execute(f"INSERT INTO company_versions ({cols_sql}) VALUES ({marks})", values)

    return True


def upsert_group(conn, group_id, group_name, *, commit: bool = True) -> bool:
    """обычный upsert, название группы не версионируем (просто перезаписываем)
    возвращаем True если строку создали или название поменялось"""
    if not group_id:
        raise ValueError("group_id обязателен")
    with _Tx(conn, commit) as cur:
        cur.execute(
            "INSERT INTO company_groups (group_id, group_name) VALUES (%s, %s) "
            "ON CONFLICT (group_id) DO UPDATE SET group_name = EXCLUDED.group_name "
            "WHERE company_groups.group_name IS DISTINCT FROM EXCLUDED.group_name "
            "RETURNING group_id",
            (group_id, group_name),
        )
        return cur.fetchone() is not None
