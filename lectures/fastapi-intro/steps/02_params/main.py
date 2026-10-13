"""Шаг 2. Path- и query-параметры, автоматическая валидация типов.

Запуск: uvicorn main:app --reload
"""

from typing import Annotated, Optional

from fastapi import FastAPI, Path, Query

app = FastAPI(title="Task Tracker", version="0.2.0")


@app.get("/")
async def root():
    return {"message": "Hello, FastAPI!"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Path-параметр: часть пути в фигурных скобках = аргумент функции с тем же именем.
@app.get("/hello/{name}")
async def hello(name: str, excited: bool = False):
    # excited нет в пути -> это query-параметр: /hello/anna?excited=true
    greeting = f"Привет, {name}"
    return {"greeting": greeting + ("!!!" if excited else ".")}


# Аннотация типа = преобразование + валидация. /square/abc -> 422.
@app.get("/square/{number}")
async def square(number: int):
    return {"number": number, "square": number**2}


# Ограничения на параметры: Path(...) и Query(...) внутри Annotated.
@app.get("/tasks/{task_id}")
async def get_task_stub(task_id: Annotated[int, Path(ge=1, description="ID задачи")]):
    return {"task_id": task_id}


@app.get("/search")
async def search(
    q: Annotated[str, Query(min_length=2, max_length=50)],    # обязательный
    limit: Annotated[int, Query(ge=1, le=100)] = 10,          # со значением по умолчанию
    tag: Optional[str] = None,                                # необязательный
):
    return {"q": q, "limit": limit, "tag": tag}
