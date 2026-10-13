"""Шаг 6. Middleware и CORS.

Запуск (из этой папки): uvicorn main:app --reload
Демо CORS: в папке cors-demo запустить `python -m http.server 5500`
и открыть http://localhost:5500
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from routers import system, tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("task-tracker")

app = FastAPI(title="Task Tracker", version="0.6.0")


# Middleware — код, который выполняется вокруг КАЖДОГО запроса:
# до обработчика (request) и после него (response).
@app.middleware("http")
async def log_and_time(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.perf_counter()

    response = await call_next(request)  # дальше по цепочке -> роутер -> обработчик

    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    logger.info("%s %s -> %s (%.2f ms) id=%s", request.method, request.url.path,
                response.status_code, elapsed_ms, request_id)
    return response


# CORS: разрешаем браузеру ходить к API со страниц с других origin.
# Middleware, добавленный последним, оказывается самым внешним, поэтому
# CORS отвечает на preflight (OPTIONS) раньше всех остальных.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
)

app.include_router(system.router)
app.include_router(tasks.router)
