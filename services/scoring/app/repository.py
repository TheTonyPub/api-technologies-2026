"""Данные для скоринга (владелец: Фёдор)."""
import psycopg

from platform_common.errors import ApiError

from .config import settings

SQL_COMPANY = """
    SELECT inn, registration_date, okved_code, status, group_id, data_as_of
    FROM company_snapshot WHERE inn = %s
"""
SQL_GROUP = "SELECT inn, is_bank_client FROM company_snapshot WHERE group_id = %s ORDER BY inn"


def load_company_for_scoring(inn: str) -> dict | None:
    """None, если компании нет в company_snapshot (-> 404 COMPANY_NOT_FOUND). Иначе:
      {"company": {"inn", "reg_date": date, "okved": str, "status": str},
       "members": [{"inn", "is_bank_client": bool}, ...]   # вся группа, включая саму компанию; [] если группы нет
       "data_as_of": datetime}
    SQL: строка из company_snapshot по inn; если group_id не NULL — все строки с этим group_id."""
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            row = conn.execute(SQL_COMPANY, (inn,)).fetchone()
            if row is None:
                return None
            inn, reg_date, okved, status, group_id, data_as_of = row
            members = []
            if group_id:  # группу читаем целиком, сама компания в ней тоже есть
                members = [{"inn": m_inn, "is_bank_client": bool(is_client)}
                           for m_inn, is_client in conn.execute(SQL_GROUP, (group_id,)).fetchall()]
    except psycopg.Error:
        # база лежит, отдаём 503 по контракту, а не 500
        raise ApiError(503, "SERVICE_UNAVAILABLE", "База данных недоступна") from None

    return {
        "company": {"inn": inn, "reg_date": reg_date, "okved": okved, "status": status},
        "members": members,
        "data_as_of": data_as_of,
    }
