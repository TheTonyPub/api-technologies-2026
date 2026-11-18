"""История версий компании и изменения её полей."""
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .store import connect, fetch_dicts

router = APIRouter()

SERVICE = {"id", "valid_from", "valid_to", "is_current", "attrs_hash"}


def diff_versions(prev: dict | None, cur: dict) -> list[dict]:
    if prev is None:
        return []
    keys = sorted((set(prev) | set(cur)) - SERVICE)
    return [{"field": k, "old": prev.get(k), "new": cur.get(k)} for k in keys if prev.get(k) != cur.get(k)]


@router.get("/v1/internal/companies/{inn}/history")
def company_history(inn: str, request: Request):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM company_versions WHERE inn = %s ORDER BY valid_from, id", (inn,))
            rows = fetch_dicts(cur)
    finally:
        conn.close()
    if not rows:
        return JSONResponse(
            status_code=404,
            content={"code": "COMPANY_NOT_FOUND", "message": f"Компания {inn} не найдена",
                     "traceId": request.headers.get("X-Request-Id")},
        )
    versions, prev = [], None
    for r in rows:
        versions.append({
            "validFrom": r["valid_from"], "validTo": r["valid_to"], "isCurrent": r["is_current"],
            "changedFields": diff_versions(prev, r),
            "attrs": {k: v for k, v in r.items() if k not in SERVICE},
        })
        prev = r
    return JSONResponse(content=jsonable_encoder({"inn": inn, "versionsCount": len(versions), "versions": versions}))
