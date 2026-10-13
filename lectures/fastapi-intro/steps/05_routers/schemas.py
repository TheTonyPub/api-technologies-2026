"""Pydantic-модели (схемы) запросов и ответов."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
    title: Optional[str] = Field(default=None, min_length=3, max_length=100, examples=["Провести семинар"])
    description: Optional[str] = Field(default=None, max_length=1000)
    priority: Optional[Priority] = Field(default=None, examples=["low"])
    estimate_hours: Optional[float] = Field(default=None, gt=0, le=40)
    done: Optional[bool] = Field(default=None, examples=[True])

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
