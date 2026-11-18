"""Счётчики PostgreSQL и Redis и состояние сборки витрины."""
from fastapi import APIRouter

from . import cache, pipeline
from .store import connect

router = APIRouter()


@router.get("/status")
def status():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE is_bank_client), max(data_as_of) "
                        "FROM company_snapshot")
            companies, clients, as_of = cur.fetchone()
    finally:
        conn.close()
    return {
        "companies": companies,
        "bank_clients": clients,
        "redis_keys": cache.count_keys(),
        "data_as_of": (pipeline.state["data_as_of"] or as_of),
        "ready": bool(pipeline.state["built"]),
        "last_error": pipeline.state["last_error"],
    }
