from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="User Service")


class UserIn(BaseModel):
    """Тело запроса POST и PUT."""
    name: str = Field(min_length=1, max_length=100, examples=["Anna"])
    age: int = Field(ge=0, le=150, examples=[25])
    sex: Literal["male", "female"] = Field(examples=["female"])


class UserOut(UserIn):
    """Ответ: пользователь вместе с его id."""
    id: int


# Простая «база» в памяти: {id: UserOut}
users_db: dict[int, UserOut] = {}
next_id = 1


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello, API is working!"}


@app.post("/v1/user", status_code=201)
def create_user(user: UserIn) -> UserOut:
    global next_id
    new_user = UserOut(id=next_id, **user.model_dump())
    users_db[next_id] = new_user
    next_id += 1
    return new_user


@app.get("/v1/user/{user_id}")
def get_user(user_id: int) -> UserOut:
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return users_db[user_id]


@app.put("/v1/user/{user_id}")
def update_user(user_id: int, user: UserIn) -> UserOut:
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    users_db[user_id] = UserOut(id=user_id, **user.model_dump())
    return users_db[user_id]


@app.delete("/v1/user/{user_id}", status_code=204)
def delete_user(user_id: int) -> None:
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    del users_db[user_id]
