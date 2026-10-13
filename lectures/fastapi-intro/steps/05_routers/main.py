"""Шаг 5. Разбиваем приложение на роутеры.

Структура:
    main.py           — создаём app и подключаем роутеры
    schemas.py        — Pydantic-модели
    storage.py        — «база» в памяти
    routers/tasks.py  — эндпоинты /v1/tasks
    routers/system.py — /health

Запуск (из этой папки): uvicorn main:app --reload
"""

from fastapi import FastAPI

from routers import system, tasks

app = FastAPI(title="Task Tracker", version="0.5.0")

app.include_router(system.router)
app.include_router(tasks.router)
