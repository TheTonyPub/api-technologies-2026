"""REST API для управления задачами — ДЗ семинара 6."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

class TaskData(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=100,
        examples=["Подготовить презентацию", "Обновить презентацию"],
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        examples=[
            "Подготовить слайды к семинару",
            "Добавить заключительный слайд",
        ],
    )
    priority: int = Field(ge=1, le=5, examples=[3, 4])

class Task(TaskData):
    task_id: int = Field(ge=1, examples=[1])

class ErrorResponse(BaseModel):
    detail: str

app = FastAPI(title="Task Service", version="1.0.0")

tasks: dict[int, Task] = {}
next_task_id = 1

@app.post(
    "/v1/tasks",
    status_code=201,
    response_model=dict[str, int],
)
async def create_task(payload: TaskData) -> dict[str, int]:
    global next_task_id

    task = Task(task_id=next_task_id, **payload.model_dump())
    tasks[next_task_id] = task
    next_task_id += 1
    return {"task_id": task.task_id}

@app.get(
    "/v1/tasks/{task_id}",
    response_model=Task,
    responses={
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
)
async def get_task(task_id: int) -> Task:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    return tasks[task_id]

@app.put(
    "/v1/tasks/{task_id}",
    response_model=Task,
    responses={
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
)
async def update_task(task_id: int, payload: TaskData) -> Task:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    task.title = payload.title
    task.description = payload.description
    task.priority = payload.priority
    return task

@app.delete(
    "/v1/tasks/{task_id}",
    status_code=204,
    response_model=None,
    responses={
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
)
async def delete_task(task_id: int) -> None:
    if tasks.pop(task_id, None) is None:
        raise HTTPException(status_code=404, detail="Task not found")
