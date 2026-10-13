"""Шаг 1. Минимальное приложение FastAPI.

Запуск (из этой папки):
    uvicorn main:app --reload
Открыть: http://localhost:8000/docs
"""

from fastapi import FastAPI

# app — ASGI-приложение. Именно его ищет uvicorn по строке "main:app":
# модуль main.py, переменная app.
app = FastAPI(title="Task Tracker", version="0.1.0")


# Декоратор связывает HTTP-метод + путь с функцией-обработчиком.
@app.get("/")
async def root():
    # dict автоматически сериализуется в JSON.
    return {"message": "Hello, FastAPI!"}


# Обработчик может быть обычной функцией (def): FastAPI запустит её в пуле потоков.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
