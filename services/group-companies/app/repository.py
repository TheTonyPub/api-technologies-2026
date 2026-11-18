"""Доступ к данным Group Companies (владелец: Павел)."""
import psycopg
from psycopg.rows import dict_row

from platform_common.errors import ApiError

from .config import settings


def get_group(inn: str) -> dict | None:
    """Вернуть None, если компании с таким ИНН нет в company_snapshot (-> 404 COMPANY_NOT_FOUND).
    Иначе dict:
      {"group_id": str | None, "group_name": str | None,
       "rows": [строки company_snapshot всех компаний группы, включая запрошенную; [] если группы нет],
       "data_as_of": datetime}
    SQL: SELECT group_id, group_name, data_as_of FROM company_snapshot WHERE inn=%s;
         SELECT * FROM company_snapshot WHERE group_id=%s ORDER BY inn;"""
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            company = conn.execute(
                "SELECT group_id, group_name, data_as_of FROM company_snapshot WHERE inn = %s",
                (inn,),
            ).fetchone()
            if company is None:
                return None
            rows = []
            if company["group_id"] is not None:
                rows = conn.execute(
                    "SELECT inn, short_name, status, group_relation, is_bank_client "
                    "FROM company_snapshot WHERE group_id = %s ORDER BY inn",
                    (company["group_id"],),
                ).fetchall()
            return {**company, "rows": rows}
    except psycopg.Error:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "База данных недоступна") from None
