"""Шаг 4. CRUD с хранением в словаре.

Запуск: uvicorn main:app --reload
"""

from datetime import datetime
from enum import Enum
from itertools import count
from typing import Annotated, Optional

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel, Field, model_validator

app = FastAPI(title="Task Tracker", version="0.4.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Модели -----------------------------------------------------------------


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=100, examples=["Подготовить семинар"])
    description: Optional[str] = Field(default=None, max_length=1000, examples=["Слайды + live coding"])
    priority: Priority = Field(default=Priority.MEDIUM, examples=["high"])
    estimate_hours: float = Field(default=1.0, gt=0, le=40, examples=[2.5])


class TaskUpdate(BaseModel):
    # Для частичного изменения все поля необязательные.
    title: Optional[str] = Field(default=None, min_length=3, max_length=100, examples=["Провести семинар"])
    description: Optional[str] = Field(default=None, max_length=1000)
    priority: Optional[Priority] = Field(default=None, examples=["low"])
    estimate_hours: Optional[float] = Field(default=None, gt=0, le=40)
    done: Optional[bool] = Field(default=None, examples=[True])

    # Валидатор уровня модели: тело {} или из одних null не пропускаем.
    @model_validator(mode="after")
    def require_any_field(self) -> "TaskUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Нужно передать хотя бы одно поле")
        return self


class TaskResponse(TaskCreate):
    task_id: int = Field(examples=[1])
    done: bool = False
    created_at: datetime


class ErrorResponse(BaseModel):
    detail: str


# --- «База данных» ------------------------------------------------------------
# Словарь в памяти: ключ — task_id, значение — объект. Живёт, пока жив процесс.

tasks: dict[int, TaskResponse] = {}
task_ids = count(start=1)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Задача не найдена"}}


def get_or_404(task_id: int) -> TaskResponse:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


# --- Эндпоинты ----------------------------------------------------------------


@app.post("/v1/tasks", response_model=TaskResponse, status_code=201)
async def create_task(payload: TaskCreate) -> TaskResponse:
    task = TaskResponse(task_id=next(task_ids), created_at=datetime.now(), **payload.model_dump())
    tasks[task.task_id] = task
    return task


@app.get("/v1/tasks", response_model=list[TaskResponse])
async def list_tasks(
    done: Optional[bool] = None,
    priority: Optional[Priority] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TaskResponse]:
    result = list(tasks.values())
    if done is not None:
        result = [t for t in result if t.done == done]
    if priority is not None:
        result = [t for t in result if t.priority == priority]
    return result[:limit]


@app.get("/v1/tasks/{task_id}", response_model=TaskResponse, responses=NOT_FOUND)
async def get_task(task_id: Annotated[int, Path(ge=1)]) -> TaskResponse:
    return get_or_404(task_id)


@app.put("/v1/tasks/{task_id}", response_model=TaskResponse, responses=NOT_FOUND)
async def update_task(task_id: Annotated[int, Path(ge=1)], payload: TaskUpdate) -> TaskResponse:
    task = get_or_404(task_id)
    # exclude_none=True: берём только поля, которые клиент реально прислал (не null).
    updated = task.model_copy(update=payload.model_dump(exclude_none=True))
    tasks[task_id] = updated
    return updated


@app.delete("/v1/tasks/{task_id}", status_code=204, response_model=None, responses=NOT_FOUND)
async def delete_task(task_id: Annotated[int, Path(ge=1)]) -> None:
    get_or_404(task_id)
    del tasks[task_id]
