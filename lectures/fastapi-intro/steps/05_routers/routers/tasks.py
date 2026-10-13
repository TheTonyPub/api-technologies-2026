"""Роутер задач: все пути начинаются с /v1/tasks."""

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from schemas import ErrorResponse, Priority, TaskCreate, TaskResponse, TaskUpdate
from storage import task_ids, tasks

# prefix и tags применяются ко всем эндпоинтам роутера.
router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Задача не найдена"}}

TaskId = Annotated[int, Path(ge=1)]


def get_or_404(task_id: int) -> TaskResponse:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(payload: TaskCreate) -> TaskResponse:
    task = TaskResponse(task_id=next(task_ids), created_at=datetime.now(), **payload.model_dump())
    tasks[task.task_id] = task
    return task


@router.get("", response_model=list[TaskResponse])
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


@router.get("/{task_id}", response_model=TaskResponse, responses=NOT_FOUND)
async def get_task(task_id: TaskId) -> TaskResponse:
    return get_or_404(task_id)


@router.put("/{task_id}", response_model=TaskResponse, responses=NOT_FOUND)
async def update_task(task_id: TaskId, payload: TaskUpdate) -> TaskResponse:
    task = get_or_404(task_id)
    updated = task.model_copy(update=payload.model_dump(exclude_none=True))
    tasks[task_id] = updated
    return updated


@router.delete("/{task_id}", status_code=204, response_model=None, responses=NOT_FOUND)
async def delete_task(task_id: TaskId) -> None:
    get_or_404(task_id)
    del tasks[task_id]
