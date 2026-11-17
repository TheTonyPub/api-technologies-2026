"""подключение к Postgres для новых модулей Enrichment
todo: сверить имена переменных (DATABASE_URL / POSTGRES_*) с .env.example
если в проекте уже есть общий get_conn(), бери его вместо connect()
"""
import os

try:
    import psycopg as pg
except ImportError:  # pragma: no cover
    import psycopg2 as pg


def dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "postgresql://{u}:{p}@{h}:{port}/{d}".format(
        u=os.getenv("POSTGRES_USER", "spark"),
        p=os.getenv("POSTGRES_PASSWORD", "spark"),
        h=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        d=os.getenv("POSTGRES_DB", "spark"),
    )


def connect():
    return pg.connect(dsn())


def fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
