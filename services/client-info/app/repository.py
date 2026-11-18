"""Доступ к данным Client Info (владелец: Савелий)."""
import json
import logging

import psycopg
import redis
from psycopg.rows import dict_row
from redis.backoff import NoBackoff
from redis.retry import Retry

from platform_common.errors import ApiError
from platform_common.mapping import to_company_info

from .config import settings

log = logging.getLogger(__name__)
cache = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.15,
                            socket_timeout=0.15, retry=Retry(NoBackoff(), 0))


def get_company_info(inn: str) -> tuple[dict | None, str]:
    """Вернуть карточку и результат поиска в кэше. Ошибка Redis считается промахом."""
    key = f"company:{inn}"
    try:
        raw = cache.get(key)
        if raw is not None:
            doc = json.loads(raw)
            if isinstance(doc, dict) and doc.get("inn") == inn:
                return doc, "HIT"
    except (redis.RedisError, ValueError):
        log.warning("Не удалось прочитать карточку из Redis")

    try:
        with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as conn:
            row = conn.execute("SELECT * FROM company_snapshot WHERE inn = %s", (inn,)).fetchone()
    except psycopg.Error:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "База данных недоступна") from None

    if row is None:
        return None, "MISS"
    doc = to_company_info(row)
    try:
        # Если Enrichment уже обновил карточку, сохраняем его более свежую запись.
        cache.set(key, json.dumps(doc, ensure_ascii=False), ex=settings.cache_ttl_seconds, nx=True)
    except redis.RedisError:
        log.warning("Не удалось записать карточку в Redis")
    return doc, "MISS"
