"""Enrichment Service (владелец: Артём).
Ждёт окончания первичной загрузки Loader и поддерживает актуальный срез."""
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .history import router as history_router
from .pipeline import run_forever
from .status import router as status_router

logging.basicConfig(level=logging.INFO)
@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    worker = threading.Thread(target=run_forever, args=(stop,), daemon=True, name="enrichment")
    worker.start()
    try:
        yield
    finally:
        stop.set()
        await asyncio.to_thread(worker.join, 1)


app = FastAPI(title="enrichment", lifespan=lifespan)
app.include_router(status_router)
app.include_router(history_router)


@app.get("/health")
def health():
    return {"status": "ok"}
