"""Мок внешнего бюро данных о клиентах «ДатаПрофиль». Путь на сервере: /client-data."""

from __future__ import annotations

import asyncio
import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, Path, Request, Response
from pydantic import BaseModel, Field

from ..common import bank
from ..common import reference as ref
from ..common.core import ApiError, RateLimiter, create_app, rng_for, team_from_key

DESCRIPTION = """Вымышленное коммерческое бюро данных **«ДатаПрофиль»**. Банк покупает у него сведения о
физлицах и риск-оценки по договору; клиент даёт согласие на обработку данных при открытии счёта.

Откуда у бюро данные (легенда):
* **Демография и адреса** — анкеты клиентов партнёров (банки, МФО, страховые), сверка с открытыми реестрами.
* **Стаж номера телефона** — данные операторов связи: сколько месяцев номер принадлежит этому человеку.
* **Занятость и доход** — диапазоны по данным партнёров и самозанятых; точных сумм бюро не раскрывает.
* **Стоп-лист** — консорциум банков-партнёров: люди, чьи счета использовались для вывода похищенных денег.
* **Риски регионов и мерчантов** — доля подтверждённого мошенничества по операциям партнёров за 12 месяцев.

**Кому нужен.** Кейс «Антифрод»: обогащение профиля клиента (ETL → Redis) и признаки `geo_risk`,
`merchant_risk` для ML-модели. Сервис платный и медленный (200–600 мс, 20 запросов/с на ключ), поэтому
звать его на каждую транзакцию в SLA 100 мс нельзя: данные нужно забирать заранее."""

app = create_app(
    "Мок бюро данных о клиентах «ДатаПрофиль»", DESCRIPTION,
    tags=[{"name": "persons", "description": "Сведения о физлицах. Кейс: Антифрод (профиль клиента)."},
          {"name": "risk", "description": "Риск-оценки регионов и мерчантов. Кейс: Антифрод (geo_risk, merchant_risk)."}],
)
limiter = RateLimiter(int(os.getenv("CLIENT_DATA_RPS", "20")))
LATENCY = (0.2, 0.6) if os.getenv("CLIENT_DATA_LATENCY", "on") == "on" else (0, 0)


async def team(request: Request, response: Response) -> str:
    t = team_from_key(request.headers.get("X-API-Key"))
    left = limiter.check(t)
    response.headers["X-RateLimit-Limit"] = str(limiter.per_second)
    response.headers["X-RateLimit-Remaining"] = str(left)
    if LATENCY[1]:
        await asyncio.sleep(random.uniform(*LATENCY))
    return t


class PersonOut(BaseModel):
    client_id: str = Field(examples=["cl-000001"])
    age: int | None = Field(description="Полных лет")
    gender: Literal["male", "female"] | None
    registration_region_code: str | None = Field(description="Регион регистрации по паспорту")
    residence_region_code: str | None = Field(description="Регион фактического проживания")
    city: str | None
    phone_tenure_months: int | None = Field(description="Сколько месяцев номер телефона принадлежит человеку")
    employment_type: Literal["employed", "self_employed", "entrepreneur", "unemployed", "retired", "student"] | None
    income_band: Literal["low", "medium", "high"] | None
    in_stop_list: bool = Field(description="Есть в стоп-листе консорциума (дропперы)")
    sources: list[Literal["partners", "telecom", "registries", "consortium"]]
    updated_at: datetime


class PersonsBatchIn(BaseModel):
    client_ids: list[str] = Field(min_length=1, max_length=100, examples=[["cl-000001", "cl-000002"]])


class PersonsBatchOut(BaseModel):
    items: list[PersonOut]
    not_found: list[str]


class RegionRiskOut(BaseModel):
    region_code: str
    region_name: str
    risk_score: float = Field(ge=0, le=1, description="Это и есть признак geo_risk для модели антифрода")
    risk_category: Literal["low", "medium", "high"]
    fraud_rate_12m: float = Field(description="Доля мошеннических операций в регионе за 12 месяцев")
    updated_at: date


class MerchantRiskOut(BaseModel):
    merchant_id: str
    name: str
    mcc: str
    mcc_description: str
    region_code: str
    risk_score: float = Field(ge=0, le=1, description="Это и есть признак merchant_risk для модели антифрода")
    risk_category: Literal["low", "medium", "high"]
    last_complaint_date: date | None
    updated_at: date


def person(client_id: str) -> dict | None:
    c = bank.client_by_id(client_id)
    if not c:
        return None
    r = rng_for("bureau", c.idx)
    if r.random() < 0.02:
        return None  # бюро ничего не знает о человеке
    today = date.today()
    age = today.year - c.birth_date.year - ((today.month, today.day) < (c.birth_date.month, c.birth_date.day))
    residence = c.home_region if r.random() < 0.85 else r.choices(ref.REGION_CODES, weights=ref.REGION_WEIGHTS)[0]
    if age >= 63 and r.random() < 0.8:
        emp = "retired"
    elif age < 23 and r.random() < 0.6:
        emp = "student"
    else:
        emp = r.choices(["employed", "self_employed", "entrepreneur", "unemployed"], weights=[70, 12, 8, 10])[0]
    income = {"mass": r.choices(["low", "medium"], [55, 45])[0], "affluent": "medium", "premium": "high"}[c.segment]
    out = {
        "client_id": c.client_id, "age": age, "gender": c.gender,
        "registration_region_code": c.home_region, "residence_region_code": residence,
        "city": ref.REGIONS[residence][1], "phone_tenure_months": int(min(age - 14, 25) * 12 * r.random()) + 1,
        "employment_type": emp, "income_band": income, "in_stop_list": r.random() < 0.005,
        "sources": sorted(r.sample(["partners", "telecom", "registries", "consortium"], r.randint(2, 4))),
        "updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc) - timedelta(hours=r.randint(0, 24 * 90)),
    }
    if r.random() < 0.1:  # неполные данные
        for k in r.sample(["age", "residence_region_code", "city", "phone_tenure_months", "employment_type",
                           "income_band"], r.randint(1, 3)):
            out[k] = None
        if out["residence_region_code"] is None:
            out["city"] = None
    return out


@app.get("/v1/persons/{client_id}", tags=["persons"], response_model=PersonOut,
         summary="Сведения о физлице",
         description="Кейс Антифрод: обогащение профиля клиента (ETL/Enrichment). Ключ — `client_id` из АБС. "
                     "Примерно у 10% людей часть полей `null`, у 2% бюро нет данных (404 `PERSON_NOT_FOUND`).")
async def get_person(client_id: str = Path(examples=["cl-000001"]), t: str = Depends(team)):
    p = person(client_id)
    if not p:
        raise ApiError(404, "PERSON_NOT_FOUND", f"У бюро нет сведений о {client_id}")
    return p


@app.post("/v1/persons:batch", tags=["persons"], response_model=PersonsBatchOut,
          summary="Сведения о физлицах пачкой (до 100)",
          description="Кейс Антифрод: то же, что GET, для пакетной загрузки в ETL. Считается за один запрос.")
async def persons_batch(body: PersonsBatchIn, t: str = Depends(team)):
    items, missing = [], []
    for cid in body.client_ids:
        p = person(cid)
        (items.append(p) if p else missing.append(cid))
    return {"items": items, "not_found": missing}


@app.get("/v1/regions/{region_code}/risk", tags=["risk"], response_model=RegionRiskOut,
         summary="Риск региона (geo_risk)",
         description="Кейс Антифрод: `risk_score` региона операции (`region_code` из транзакции АБС) — "
                     "это признак `geo_risk` для модели. Меняется редко: кэшируйте.")
async def region(region_code: str = Path(pattern=r"^\d{2}$", examples=["77"]), t: str = Depends(team)):
    if region_code not in ref.REGIONS:
        raise ApiError(404, "REGION_NOT_FOUND", f"Нет данных по региону {region_code}")
    risk = bank.region_risk(region_code)
    return {"region_code": region_code, "region_name": ref.REGIONS[region_code][0], "risk_score": risk,
            "risk_category": bank.risk_category(risk), "fraud_rate_12m": round(risk * 0.06, 4),
            "updated_at": date(2026, 10, 1)}


@app.get("/v1/regions", tags=["risk"], response_model=list[RegionRiskOut],
         summary="Риски всех регионов",
         description="Кейс Антифрод: справочник целиком, чтобы один раз положить в Redis.")
async def regions(t: str = Depends(team)):
    return [await region(code, t) for code in ref.REGION_CODES]


@app.get("/v1/merchants/{merchant_id}/risk", tags=["risk"], response_model=MerchantRiskOut,
         summary="Риск мерчанта (merchant_risk)",
         description="Кейс Антифрод: `risk_score` мерчанта из транзакции — признак `merchant_risk`. "
                     "Для операций без мерчанта (переводы, банкомат) признак считайте 0.")
async def merchant(merchant_id: str = Path(examples=["m-00001"]), t: str = Depends(team)):
    m = bank.merchant_by_id(merchant_id)
    if not m:
        raise ApiError(404, "MERCHANT_NOT_FOUND", f"Нет данных по мерчанту {merchant_id}")
    return {"merchant_id": m.merchant_id, "name": m.name, "mcc": m.mcc, "mcc_description": ref.MCC[m.mcc][0],
            "region_code": m.region, "risk_score": m.risk, "risk_category": bank.risk_category(m.risk),
            "last_complaint_date": m.last_complaint, "updated_at": date(2026, 10, 1)}


class MerchantPage(BaseModel):
    items: list[MerchantRiskOut]
    nextCursor: str | None


@app.get("/v1/merchants/risk", tags=["risk"], response_model=MerchantPage,
         summary="Риски всех мерчантов постранично",
         description="Кейс Антифрод: выгрузить справочник мерчантов в Redis одним проходом.")
async def merchants_page(t: str = Depends(team), limit: int = 200, cursor: str | None = None):
    start = int(cursor) if cursor and cursor.isdigit() else 0
    limit = max(1, min(limit, 500))
    ms = bank.merchants()[start:start + limit]
    items = [await merchant(m.merchant_id, t) for m in ms]
    nxt = str(start + limit) if start + limit < bank.N_MERCHANTS else None
    return {"items": items, "nextCursor": nxt}
