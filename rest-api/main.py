"""
REST API для сервиса пользователей (User Service).

Методы:
    POST   /v1/user          — создать пользователя, вернуть его идентификатор
    GET    /v1/user/{id}     — получить пользователя
    PUT    /v1/user/{id}     — изменить пользователя
    DELETE /v1/user/{id}     — удалить пользователя

Запуск: uvicorn main:app --reload  →  http://localhost:8000/docs
"""

from typing import Optional, Literal
from enum import Enum 

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4


# --- Модели запросов -------------------------------------------------------
# Каждое поле описываем через Field с ограничениями и examples.
class SexEnum(str, Enum):
    male = "male"
    female = "female"


class UserCreate(BaseModel):
    """Модель для создания пользователя (POST)."""
    age: int = Field(
        ..., 
        ge=0, 
        le=120, 
        description="Возраст пользователя",
        examples=[25]
    )
    sex: SexEnum = Field(
        ..., 
        description="Пол пользователя",
        examples=["male"]
    )


class UserUpdate(BaseModel):
    """Модель для обновления пользователя (PUT). 
    Поля необязательные, чтобы можно было менять только часть данных."""
    age: Optional[int] = Field(
        default=None, 
        ge=0, 
        le=120, 
        description="Возраст пользователя",
        examples=[30]
    )
    sex: Optional[Literal["male", "female"]] = Field(
        default=None, 
        description="Пол пользователя",
        examples=["female"]
    )


# --- Модели ответов --------------------------------------------------------


class UserCreated(BaseModel):
    """Ответ POST обязан содержать идентификатор созданного объекта."""
    user_id: int


class UserResponse(UserCreated):
    """Полная модель ответа для GET и PUT."""
    age: int
    sex: SexEnum


class ErrorResponse(BaseModel):
    """Модель для описания ошибок в Swagger."""
    detail: str


app = FastAPI(title="User Service", version="1.0.0")

# «База» данных — словарь в памяти: ключ — user_id, значение — объект.
# Базу данных (SQLite и т. п.) не используем.
users: dict[int, UserResponse] = {}


@app.post(
    "/v1/user",
    status_code=201,
    response_model=UserCreated,
)
async def create_user(payload: UserCreate) -> UserCreated:
    """Создать нового пользователя."""
    new_id = uuid4().int
    user_obj = UserResponse(user_id=new_id, **payload.model_dump())
    users[new_id] = user_obj
    return UserCreated(user_id=new_id)


@app.get(
    "/v1/user/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: int) -> UserResponse:
    """Получить пользователя по ID."""
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    return users[user_id]


@app.put(
    "/v1/user/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def update_user(user_id: int, payload: UserUpdate) -> UserResponse:
    """Изменить пользователя и вернуть его новое состояние."""
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Получаем текущие данные
    current_user = users[user_id]
    
    # Обновляем только те поля, которые переданы (не None)
    update_data = payload.model_dump(exclude_unset=True)
    updated_user = current_user.model_copy(update=update_data)
    
    users[user_id] = updated_user
    return updated_user


@app.delete(
    "/v1/user/{user_id}",
    status_code=204,
    response_model=None,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def delete_user(user_id: int) -> None:
    """Удалить пользователя или вернуть 404."""
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    del users[user_id]
    return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
