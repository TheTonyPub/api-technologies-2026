"""REST API для управления задачами — ДЗ семинара 6."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=100,
        examples=["Подготовить презентацию"],
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        examples=["Подготовить слайды к семинару"],
    )
    priority: int = Field(
        ge=1,
        le=5,
        examples=[3],
    )


class TaskUpdate(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=100,
        examples=["Обновить презентацию"],
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        examples=["Добавить заключительный слайд"],
    )
    priority: int = Field(
        ge=1,
        le=5,
        examples=[4],
    )


class TaskCreated(BaseModel):
    task_id: int = Field(ge=1, examples=[1])


class TaskResponse(TaskCreated):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    priority: int = Field(ge=1, le=5)


class ErrorResponse(BaseModel):
    detail: str


app = FastAPI(title="Task Service", version="1.0.0")

tasks: dict[int, TaskResponse] = {}
next_task_id = 1


@app.post(
    "/v1/tasks",
    status_code=201,
    response_model=TaskCreated,
)
async def create_task(payload: TaskCreate) -> TaskCreated:
    global next_task_id

    task = TaskResponse(
        task_id=next_task_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
    )
    tasks[next_task_id] = task
    next_task_id += 1

    return TaskCreated(task_id=task.task_id)


@app.get(
    "/v1/tasks/{task_id}",
    response_model=TaskResponse,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Task not found",
        }
    },
)
async def get_task(task_id: int) -> TaskResponse:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    return tasks[task_id]


@app.put(
    "/v1/tasks/{task_id}",
    response_model=TaskResponse,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Task not found",
        }
    },
)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
) -> TaskResponse:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = TaskResponse(
        task_id=task_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
    )
    tasks[task_id] = task

    return task


@app.delete(
    "/v1/tasks/{task_id}",
    status_code=204,
    response_model=None,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Task not found",
        }
    },
)
async def delete_task(task_id: int) -> None:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    del tasks[task_id]
