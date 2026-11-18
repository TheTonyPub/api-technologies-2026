"""Client Info Service (владелец: Савелий). Контракт: contracts/client-info-service/openapi.yaml."""
from typing import Annotated

from fastapi import FastAPI, Path, Response

from platform_common.errors import INN_PATTERN, ApiError, install

from . import repository

app = FastAPI(title="Client Info Service")
install(app)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/companies/{inn}")
def get_company(inn: Annotated[str, Path(pattern=INN_PATTERN)], response: Response):
    doc, cache_status = repository.get_company_info(inn)
    if doc is None:
        raise ApiError(404, "COMPANY_NOT_FOUND", "Компания с таким ИНН не найдена")
    response.headers["X-Cache"] = cache_status
    return doc
