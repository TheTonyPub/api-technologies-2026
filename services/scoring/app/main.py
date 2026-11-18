"""Scoring Service (владелец: Фёдор). Контракт: contracts/scoring-service/openapi.yaml."""
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import FastAPI, Path

from platform_common.errors import INN_PATTERN, ApiError, install
from platform_common.mapping import iso_utc

from . import ml_client, repository
from .config import settings
from .features import build_features

app = FastAPI(title="Scoring Service")
install(app)


def calc_date(data_as_of: datetime) -> date:
    """дата, от которой считаем companyAgeMonths

    по умолчанию берём сегодня по UTC (SCORING_AS_OF=today), так как раз написано в ТЗ.
    если Артём по tools/expected.py выяснит, что эталон считает от даты среза,
    просто ставим SCORING_AS_OF=data_as_of, код при этом не трогаем"""
    if settings.scoring_as_of == "data_as_of" and data_as_of is not None:
        return data_as_of.astimezone(timezone.utc).date()
    return datetime.now(timezone.utc).date()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/companies/{inn}/scoring")
def scoring(inn: Annotated[str, Path(pattern=INN_PATTERN)]):
    data = repository.load_company_for_scoring(inn)
    if data is None:
        raise ApiError(404, "COMPANY_NOT_FOUND", f"Компания с ИНН {inn} не найдена")
    numeric, categorical = build_features(data["company"], data["members"], as_of=calc_date(data["data_as_of"]))
    result = ml_client.predict(inn, numeric, categorical)
    return {
        "inn": inn,
        "probability": result.score,
        "modelVersion": result.model_version,
        "scoredAt": iso_utc(datetime.now(timezone.utc)),
        "dataAsOf": iso_utc(data["data_as_of"]),
    }
