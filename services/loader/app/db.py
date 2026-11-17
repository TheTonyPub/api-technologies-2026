import json

import psycopg

from .config import settings
from .store import merge_changed_inns

def connect():
    return psycopg.connect(settings.database_url, connect_timeout=5)

def get_state(key: str):
    with connect() as c:
        row = c.execute("SELECT value FROM load_state WHERE key=%s", (key,)).fetchone()
    return row[0] if row else None

def set_state(key: str, value: str):
    with connect() as c:
        c.execute(
            "INSERT INTO load_state(key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))

def counts() -> dict:
    with connect() as c:
        cur, total, groups = c.execute(
            "SELECT count(*) FILTER (WHERE is_current), count(*), "
            "count(DISTINCT group_id) FILTER (WHERE is_current) FROM company_versions").fetchone()
    return {"companies": cur, "versions": total, "groups": groups}


def current_inns() -> set[str]:
    with connect() as conn:
        rows = conn.execute("SELECT inn FROM company_versions WHERE is_current").fetchall()
    return {inn for (inn,) in rows}


def add_changed_inns(inns: list[str]) -> None:
    if not inns:
        return
    with connect() as conn:
        conn.execute("INSERT INTO load_state(key, value) VALUES ('changed_inns', '[]') "
                     "ON CONFLICT (key) DO NOTHING")
        # Блокировка строки защищает read-modify-write, включая параллельный первый вызов.
        (previous,) = conn.execute(
            "SELECT value FROM load_state WHERE key = 'changed_inns' FOR UPDATE"
        ).fetchone()
        conn.execute(
            "UPDATE load_state SET value = %s WHERE key = 'changed_inns'",
            (json.dumps(merge_changed_inns(inns, json.loads(previous))),),
        )
