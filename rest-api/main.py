from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"


class UserCreate(BaseModel):
    age: int = Field(ge=6, le=90, examples=[24])
    sex: Sex = Field(examples=["male"])


class UserUpdate(BaseModel):
    age: Optional[int] = Field(default=None, ge=6, le=90, examples=[25])
    sex: Optional[Sex] = Field(default=None, examples=["female"])

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdate":
        if self.age is None and self.sex is None:
            raise ValueError("At least one field must be provided")
        return self


class UserCreated(BaseModel):
    user_id: int


class UserResponse(UserCreated):
    age: int
    sex: Sex


class ErrorResponse(BaseModel):
    detail: str


app = FastAPI(title="User Service", version="1.0.0")

users: dict[int, UserResponse] = {}
next_id = 1


@app.post("/v1/user", status_code=201, response_model=UserCreated)
async def create_user(payload: UserCreate) -> UserCreated:
    global next_id
    user = UserResponse(user_id=next_id, age=payload.age, sex=payload.sex)
    users[user.user_id] = user
    next_id += 1
    return UserCreated(user_id=user.user_id)


@app.get(
    "/v1/user/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: int) -> UserResponse:
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    return users[user_id]


@app.put(
    "/v1/user/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def update_user(user_id: int, payload: UserUpdate) -> UserResponse:
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id] = users[user_id].model_copy(update=payload.model_dump(exclude_none=True))
    return users[user_id]


@app.delete(
    "/v1/user/{user_id}",
    status_code=204,
    response_model=None,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def delete_user(user_id: int) -> None:
    if users.pop(user_id, None) is None:
        raise HTTPException(status_code=404, detail="User not found")
