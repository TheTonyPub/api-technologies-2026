"""собираем company_snapshot одним INSERT ... SELECT ... ON CONFLICT (inn) DO UPDATE

колонки среза читаем из information_schema, то есть неважно какие бизнес-колонки добавили в 001/002
group_name берём из company_groups
is_bank_client берём из bank_clients (нет записи, значит false)
data_as_of это время сборки (параметр)
остальные колонки берём из текущей версии company_versions, если такая колонка там есть
колонка среза без источника это ошибка с понятным текстом (значит схема разошлась)
"""
import logging

log = logging.getLogger("enrichment.snapshot")

# todo: сверить с 001_init.sql
GROUP_KEY, GROUP_NAME_COL = "group_id", "group_name"
BANK_FLAG_COL = "is_bank_client"


def _cols(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
        (table,))
    return [r[0] for r in cur.fetchall()]


def build_sql(snapshot_cols, version_cols):
    select, missing = [], []
    for col in snapshot_cols:
        if col == "data_as_of":
            select.append("%s")
        elif col == "group_name":
            select.append(f'g."{GROUP_NAME_COL}"')
        elif col == "is_bank_client":
            select.append(f'COALESCE(b."{BANK_FLAG_COL}", false)')
        elif col in version_cols:
            select.append(f'v."{col}"')
        else:
            missing.append(col)
    if missing:
        raise RuntimeError(f"В company_snapshot есть колонки без источника: {missing}")
    cols_sql = ", ".join(f'"{c}"' for c in snapshot_cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in snapshot_cols if c != "inn")
    sql = (
        f"INSERT INTO company_snapshot ({cols_sql}) "
        f"SELECT {', '.join(select)} FROM company_versions v "
        f'LEFT JOIN company_groups g ON g."{GROUP_KEY}" = v."{GROUP_KEY}" '
        "LEFT JOIN bank_clients b ON b.inn = v.inn "
        "WHERE v.is_current "
        f"ON CONFLICT (inn) DO UPDATE SET {updates}"
    )
    return sql


def rebuild_snapshot(conn, as_of) -> int:
    """пересобираем срез целиком, возвращаем кол-во строк"""
    with conn.cursor() as cur:
        snap, ver = _cols(cur, "company_snapshot"), set(_cols(cur, "company_versions"))
        sql = build_sql(snap, ver)
        params = [as_of] if "data_as_of" in snap else []
        cur.execute(sql, params)
        cur.execute("SELECT count(*) FROM company_snapshot")
        total = cur.fetchone()[0]
    conn.commit()
    log.info("company_snapshot пересобран: %d строк, data_as_of=%s", total, as_of)
    return total
