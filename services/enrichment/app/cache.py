"""в Redis ключ company:{inn}, значение это JSON карточки (platform_common.mapping.to_company_info)"""
import json
import logging
import os

import redis

from .store import fetch_dicts

log = logging.getLogger("enrichment.cache")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
REDIS_URL = os.getenv("REDIS_URL") or "redis://{h}:{p}/0".format(
    h=os.getenv("REDIS_HOST", "redis"), p=os.getenv("REDIS_PORT", "6379"))
PREFIX = "company:"


def _default(v):
    """запасная сериализация на всякий случай
    dataAsOf по контракту это ISO с 'Z', его как раз должен отдавать to_company_info
    тут просто страховка от str(datetime) с пробелом"""
    import datetime as dt
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if v.tzinfo else v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


def get_redis():
    return redis.Redis.from_url(REDIS_URL, socket_timeout=3, socket_connect_timeout=3)


def publish_cards(conn, r=None) -> int:
    """кладём карточки всех компаний среза (если Redis лежит, лог и 0, исключение наружу не кидаем)"""
    from platform_common.mapping import to_company_info  # лениво, так удобнее в тестах

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM company_snapshot")
        rows = fetch_dicts(cur)
    try:
        r = r or get_redis()
        pipe = r.pipeline(transaction=False)
        for row in rows:
            info = to_company_info(row)
            if hasattr(info, "model_dump"):  # вдруг вернётся pydantic-модель
                info = info.model_dump(by_alias=True, mode="json")
            card = json.dumps(info, ensure_ascii=False, default=_default)
            pipe.set(PREFIX + row["inn"], card, ex=CACHE_TTL_SECONDS)
        pipe.execute()
        log.info("Redis: записано %d карточек, TTL %d c", len(rows), CACHE_TTL_SECONDS)
        return len(rows)
    except redis.RedisError as e:
        log.error("Redis недоступен, кэш пропущен: %s", e)
        return 0


def count_keys(r=None) -> int | None:
    try:
        r = r or get_redis()
        return sum(1 for _ in r.scan_iter(match=PREFIX + "*", count=500))
    except redis.RedisError:
        return None
