"""Работа с PostgreSQL: подключение, таблицы, сохранение данных.

Везде используем INSERT ... ON CONFLICT: если запись уже есть, дубль не создаётся.
Поэтому любую загрузку можно запускать повторно.
"""
import logging
import time

import psycopg2
from psycopg2.extras import execute_values

import config

log = logging.getLogger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id        TEXT PRIMARY KEY,
    full_name        TEXT,
    birth_date       DATE,
    gender           TEXT,
    home_region_code TEXT,
    customer_since   DATE,
    segment          TEXT,
    phone_masked     TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    client_id  TEXT,
    number     TEXT,
    currency   TEXT,
    opened_at  DATE,
    status     TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id       TEXT PRIMARY KEY,
    account_id           TEXT,
    client_id            TEXT,
    amount               NUMERIC(14, 2),
    currency             TEXT,
    timestamp            TIMESTAMPTZ,
    merchant_id          TEXT,
    mcc                  TEXT,
    channel              TEXT,
    region_code          TEXT,
    counterparty_account TEXT,
    is_fraud             BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_tx_account_time ON transactions (account_id, timestamp);

CREATE TABLE IF NOT EXISTS client_profiles (
    client_id               TEXT PRIMARY KEY,
    found                   BOOLEAN NOT NULL,   -- false: бюро ничего не знает о клиенте
    age                     INT,
    gender                  TEXT,
    registration_region_code TEXT,
    residence_region_code   TEXT,
    city                    TEXT,
    phone_tenure_months     INT,
    employment_type         TEXT,
    income_band             TEXT,
    in_stop_list            BOOLEAN,
    sources                 TEXT,
    updated_at              TIMESTAMPTZ
);

-- служебные значения: до какого момента загружены операции, курсор незаконченной загрузки и т.п.
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect():
    # Postgres в docker может подниматься не сразу, поэтому пробуем несколько раз
    for attempt in range(1, 31):
        try:
            return psycopg2.connect(
                host=config.POSTGRES_HOST, port=config.POSTGRES_PORT, dbname=config.POSTGRES_DB,
                user=config.POSTGRES_USER, password=config.POSTGRES_PASSWORD, connect_timeout=5)
        except psycopg2.OperationalError as e:
            log.warning("Postgres пока недоступен (%s), попытка %d", str(e).strip(), attempt)
            time.sleep(2)
    raise RuntimeError("не удалось подключиться к Postgres")


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------- служебные значения

def get_state(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM sync_state WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def _set_state(cur, key, value):
    cur.execute(
        "INSERT INTO sync_state (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))


def set_state(conn, key, value):
    with conn.cursor() as cur:
        _set_state(cur, key, value)
    conn.commit()


# ---------------------------------------------------------------- клиенты и счета

def save_clients(conn, clients):
    rows = [(c["client_id"], c["full_name"], c["birth_date"], c["gender"], c["home_region_code"],
             c["customer_since"], c["segment"], c["phone_masked"]) for c in clients]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO clients (client_id, full_name, birth_date, gender, home_region_code,
                                 customer_since, segment, phone_masked)
            VALUES %s
            ON CONFLICT (client_id) DO UPDATE SET
                full_name = EXCLUDED.full_name, birth_date = EXCLUDED.birth_date,
                gender = EXCLUDED.gender, home_region_code = EXCLUDED.home_region_code,
                customer_since = EXCLUDED.customer_since, segment = EXCLUDED.segment,
                phone_masked = EXCLUDED.phone_masked
        """, rows)
    conn.commit()


def get_account_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT account_id FROM accounts")
        return {row[0] for row in cur.fetchall()}


def save_accounts(conn, accounts):
    rows = [(a["account_id"], a["client_id"], a["number"], a["currency"], a["opened_at"], a["status"])
            for a in accounts]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO accounts (account_id, client_id, number, currency, opened_at, status)
            VALUES %s
            ON CONFLICT (account_id) DO UPDATE SET
                client_id = EXCLUDED.client_id, number = EXCLUDED.number, currency = EXCLUDED.currency,
                opened_at = EXCLUDED.opened_at, status = EXCLUDED.status
        """, rows)
    conn.commit()


# ---------------------------------------------------------------- операции

def save_transactions_page(conn, items, state):
    """Сохраняем страницу операций и в той же транзакции запоминаем, где остановились.

    state: словарь служебных значений, например {"tx_pass_cursor": "2026-11-05:12:3"}.
    Если сервис упадёт, то либо сохранится всё вместе, либо ничего, и курсор не разойдётся с данными.
    """
    rows = [(t["transaction_id"], t["account_id"], t["client_id"], t["amount"], t["currency"],
             t["timestamp"], t["merchant_id"], t["mcc"], t["channel"], t["region_code"],
             t["counterparty_account"], t["is_fraud"]) for t in items]
    with conn.cursor() as cur:
        if rows:
            execute_values(cur, """
                INSERT INTO transactions (transaction_id, account_id, client_id, amount, currency,
                                          timestamp, merchant_id, mcc, channel, region_code,
                                          counterparty_account, is_fraud)
                VALUES %s
                ON CONFLICT (transaction_id) DO NOTHING
            """, rows)
        for key, value in state.items():
            _set_state(cur, key, value)
    conn.commit()


def finish_transactions_pass(conn, loaded_until):
    """Загрузка дошла до конца: запоминаем время и убираем служебные значения незаконченной загрузки."""
    with conn.cursor() as cur:
        _set_state(cur, "tx_loaded_until", loaded_until)
        cur.execute("DELETE FROM sync_state WHERE key IN ('tx_pass_from', 'tx_pass_to', 'tx_pass_cursor')")
    conn.commit()


def delete_old_transactions(conn, days):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM transactions WHERE timestamp < now() - make_interval(days => %s)", (days,))
        deleted = cur.rowcount
    conn.commit()
    return deleted


def count_transactions(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions")
        return cur.fetchone()[0]


# ---------------------------------------------------------------- профили

def get_client_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT client_id FROM clients ORDER BY client_id")
        return [row[0] for row in cur.fetchall()]


def save_profiles(conn, found, not_found_ids):
    rows = [(p["client_id"], True, p.get("age"), p.get("gender"), p.get("registration_region_code"),
             p.get("residence_region_code"), p.get("city"), p.get("phone_tenure_months"),
             p.get("employment_type"), p.get("income_band"), p.get("in_stop_list"),
             ",".join(p.get("sources") or []), p.get("updated_at")) for p in found]
    # клиентов, о которых бюро ничего не знает, тоже записываем (found = false)
    rows += [(cid, False, None, None, None, None, None, None, None, None, None, None, None)
             for cid in not_found_ids]
    if not rows:
        return
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO client_profiles (client_id, found, age, gender, registration_region_code,
                                         residence_region_code, city, phone_tenure_months,
                                         employment_type, income_band, in_stop_list, sources, updated_at)
            VALUES %s
            ON CONFLICT (client_id) DO UPDATE SET
                found = EXCLUDED.found, age = EXCLUDED.age, gender = EXCLUDED.gender,
                registration_region_code = EXCLUDED.registration_region_code,
                residence_region_code = EXCLUDED.residence_region_code, city = EXCLUDED.city,
                phone_tenure_months = EXCLUDED.phone_tenure_months,
                employment_type = EXCLUDED.employment_type, income_band = EXCLUDED.income_band,
                in_stop_list = EXCLUDED.in_stop_list, sources = EXCLUDED.sources,
                updated_at = EXCLUDED.updated_at
        """, rows)
    conn.commit()


# ---------------------------------------------------------------- счётчики для /stats

def get_counts(conn):
    counts = {}
    with conn.cursor() as cur:
        for name, sql in [
            ("clients", "SELECT count(*) FROM clients"),
            ("accounts", "SELECT count(*) FROM accounts"),
            ("transactions", "SELECT count(*) FROM transactions"),
            ("profiles_found", "SELECT count(*) FROM client_profiles WHERE found"),
            ("profiles_not_found", "SELECT count(*) FROM client_profiles WHERE NOT found"),
        ]:
            cur.execute(sql)
            counts[name] = cur.fetchone()[0]
    return counts
