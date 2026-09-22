from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional

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


DB_PATH = Path(os.environ.get("USER_DB_PATH", "data/users.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                age INTEGER NOT NULL,
                sex TEXT NOT NULL CHECK (sex IN ('male', 'female'))
            )
            """
        )


app = FastAPI(title="User Service", version="1.0.0")


@app.on_event("startup")
async def startup() -> None:
    initialize_database()


@app.post("/v1/user", status_code=201, response_model=UserCreated)
async def create_user(payload: UserCreate) -> UserCreated:
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO users (age, sex) VALUES (?, ?)",
            (payload.age, payload.sex.value),
        )
    return UserCreated(user_id=cursor.lastrowid)


@app.get("v1/user/{user_id}", status_code=200, response_model=UserResponse)
async def get_user_data(user_id: int) -> UserResponse:
    with database() as connection:
        row = connection.execute(
            "SELECT user_id, age, sex FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(user_id=row["user_id"], age=row["age"], sex=row["sex"])

@app.put("/v1/user/{user_id}", status_code=201, response_model=UserResponse)
async def update_user(user_id: int, payload: UserUpdate) -> UserResponse:
    updates: list[str] = []
    values: list[int | str] = []
    if payload.age is not None:
        updates.append("age = ?")
        values.append(payload.age)
    if payload.sex is not None:
        updates.append("sex = ?")
        values.append(payload.sex.value)
    values.append(user_id)

    with database() as connection:
        cursor = connection.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        row = connection.execute(
            "SELECT user_id, age, sex FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

    return UserResponse(user_id=row["user_id"], age=row["age"], sex=row["sex"])
