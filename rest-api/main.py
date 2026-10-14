"""Шаблон REST-сервиса для ДЗ семинара 6.

Ориентир — user-service из семинара 3 (ветка seminar/03-api-interaction).
Можно оставить «пользователей», а можно придумать свою предметную область:
переименуйте модели и пути, но сохраните четыре метода и форму CRUD:

    POST   /v1/<resource>          — создать объект, вернуть его идентификатор
    GET    /v1/<resource>/{id}     — получить объект
    PUT    /v1/<resource>/{id}     — изменить объект
    DELETE /v1/<resource>/{id}     — удалить объект

Запуск: uvicorn main:app --reload  →  http://localhost:8000/docs
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# --- Модели запросов -------------------------------------------------------
# Каждое поле описывайте через Field с ограничениями (ge/le, min_length,
# max_length, pattern, ...) и examples: CI строит тестовые запросы по схеме
# OpenAPI и в первую очередь берёт значения из examples.


class ItemCreate(BaseModel):
    # TODO: замените на поля своей модели.
    name: str = Field(min_length=1, max_length=100, examples=["example"])


class ItemUpdate(BaseModel):
    # TODO: поля для изменения (обычно те же, но необязательные).
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, examples=["updated"])


# --- Модели ответов --------------------------------------------------------


class ItemCreated(BaseModel):
    # Ответ POST обязан содержать идентификатор созданного объекта.
    item_id: int


class ItemResponse(ItemCreated):
    name: str


class ErrorResponse(BaseModel):
    detail: str


app = FastAPI(title="Item Service", version="1.0.0")

# «База» данных — словарь в памяти: ключ — item_id, значение — объект.
# Базу данных (SQLite и т. п.) не используем.
items: dict[int, ItemResponse] = {}


@app.post(
    "/v1/item",
    status_code=201,
    response_model=ItemCreated,
)
async def create_item(payload: ItemCreate) -> ItemCreated:
    # TODO: сохранить объект и вернуть его идентификатор.
    raise HTTPException(status_code=501, detail="Not implemented")


@app.get(
    "/v1/item/{item_id}",
    response_model=ItemResponse,
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
async def get_item(item_id: int) -> ItemResponse:
    # TODO: вернуть объект или 404, если его нет.
    raise HTTPException(status_code=501, detail="Not implemented")


@app.put(
    "/v1/item/{item_id}",
    response_model=ItemResponse,
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
async def update_item(item_id: int, payload: ItemUpdate) -> ItemResponse:
    # TODO: изменить объект и вернуть его новое состояние или 404.
    raise HTTPException(status_code=501, detail="Not implemented")


@app.delete(
    "/v1/item/{item_id}",
    status_code=204,
    response_model=None,
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
async def delete_item(item_id: int) -> None:
    # TODO: удалить объект или вернуть 404.
    raise HTTPException(status_code=501, detail="Not implemented")
