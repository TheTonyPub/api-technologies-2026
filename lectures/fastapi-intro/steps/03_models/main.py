"""Шаг 3. Модели данных на Pydantic: тело запроса, ответ, валидация через Field.

Запуск: uvicorn main:app --reload
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Task Tracker", version="0.3.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Модель запроса: что клиент присылает в теле POST.
class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=100, examples=["Подготовить семинар"])
    description: Optional[str] = Field(default=None, max_length=1000, examples=["Слайды + live coding"])
    priority: Priority = Field(default=Priority.MEDIUM, examples=["high"])
    estimate_hours: float = Field(default=1.0, gt=0, le=40, examples=[2.5])


# Модель ответа: что сервер отдаёт. Наследуем поля запроса и добавляем серверные.
class TaskResponse(TaskCreate):
    task_id: int = Field(examples=[1])
    done: bool = False
    created_at: datetime


# Аргумент с типом BaseModel = тело запроса (JSON).
# response_model фильтрует и документирует ответ.
@app.post("/v1/tasks", response_model=TaskResponse, status_code=201)
async def create_task(payload: TaskCreate) -> TaskResponse:
    return TaskResponse(task_id=1, created_at=datetime.now(), **payload.model_dump())
