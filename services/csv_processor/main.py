from __future__ import annotations

import asyncio
import csv
import io
import os
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.background import BackgroundTask


EXPECTED_COLUMNS = ["feature1", "feature2", "feature3"]
TOKEN = os.environ["PROCESSING_TOKEN"]
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "."))
security = HTTPBearer(auto_error=False)


@dataclass
class Run:
    state: str
    path: Path


runs: dict[str, Run] = {}
runs_lock = threading.Lock()
Credentials = Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)]
app = FastAPI(title="CSV Processor", version="1.0.0")


def require_token(credentials: Optional[HTTPAuthorizationCredentials]) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")
    if credentials.credentials != TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def parse_csv(raw_data: bytes) -> list[dict[str, str]]:
    try:
        text = raw_data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8") from error

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != EXPECTED_COLUMNS:
        raise HTTPException(422, "CSV columns must be feature1, feature2, feature3")

    rows = list(reader)
    if len(rows) > 100:
        raise HTTPException(422, "CSV must contain at most 100 rows")

    for row_number, row in enumerate(rows, start=2):
        try:
            for column in EXPECTED_COLUMNS[:2]:
                value = Decimal(row[column])
                if not value.is_finite():
                    raise InvalidOperation
        except (InvalidOperation, KeyError, TypeError) as error:
            raise HTTPException(422, f"Row {row_number} has invalid numeric values") from error
    return rows


def transformed_csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPECTED_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "feature1": format(Decimal(row["feature1"]) + Decimal(10), "f"),
                "feature2": format(Decimal(row["feature2"]) + Decimal(10), "f"),
                "feature3": row["feature3"][:1],
            }
        )
    return output.getvalue()


async def process_run(run_id: str, rows: list[dict[str, str]]) -> None:
    await asyncio.sleep(1)
    path = OUTPUT_DIR / f"{run_id}.csv"
    path.write_text(transformed_csv(rows), encoding="utf-8")
    with runs_lock:
        run = runs.get(run_id)
        if run is not None:
            run.state = "ready"


def delete_after_delivery(run_id: str, path: Path) -> None:
    path.unlink(missing_ok=True)
    with runs_lock:
        runs.pop(run_id, None)


@app.get("/v1/example", response_class=PlainTextResponse)
async def get_example() -> str:
    return "feature1,feature2,feature3\n1,2.5,hello\n10,0.75,world\n"


@app.post("/v1/process", status_code=status.HTTP_202_ACCEPTED)
async def process_csv(
    request: Request,
    background_tasks: BackgroundTasks,
    credentials: Credentials,
) -> dict[str, str]:
    require_token(credentials)
    if not request.headers.get("content-type", "").startswith("text/csv"):
        raise HTTPException(422, "Content-Type must be text/csv")
    rows = parse_csv(await request.body())
    run_id = str(uuid4())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with runs_lock:
        runs[run_id] = Run(state="processing", path=OUTPUT_DIR / f"{run_id}.csv")
    background_tasks.add_task(process_run, run_id, rows)
    return {"run_id": run_id}


@app.get("/v1/data/{run_id}")
async def get_processed_data(run_id: str, credentials: Credentials) -> FileResponse:
    require_token(credentials)
    with runs_lock:
        run = runs.get(run_id)
        if run is None or run.state != "ready" or not run.path.exists():
            raise HTTPException(404, "Processed data is not ready")
        run.state = "delivering"

    return FileResponse(
        run.path,
        media_type="text/csv",
        filename=f"{run_id}.csv",
        background=BackgroundTask(delete_after_delivery, run_id, run.path),
    )
