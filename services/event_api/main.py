import json
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import nats
from fastapi import FastAPI, HTTPException, status
from nats.errors import NoRespondersError, TimeoutError as NatsTimeoutError
from nats.js.errors import NotFoundError
from nats.js.api import StreamConfig, StorageType
from pydantic import BaseModel, Field


class InputRecord(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    monthly_usage: float = Field(ge=0)
    support_tickets: int = Field(ge=0)


class JobRequest(BaseModel):
    records: list[InputRecord] = Field(min_length=1, max_length=100)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.nc = await nats.connect(os.getenv("NATS_URL", "nats://nats:4222"))
    app.state.js = app.state.nc.jetstream()
    try:
        await app.state.js.stream_info("INFERENCE")
    except NotFoundError:
        try:
            await app.state.js.add_stream(
                StreamConfig(
                    name="INFERENCE",
                    subjects=["inference.request.*", "inference.result.*"],
                    storage=StorageType.FILE,
                    max_age=7 * 24 * 60 * 60,
                )
            )
        except Exception:
            # API and worker may both initialize the stream at the same time.
            await app.state.js.stream_info("INFERENCE")
    try:
        yield
    finally:
        await app.state.nc.drain()


app = FastAPI(
    title="Seminar 04 event inference",
    root_path="/events" if os.getenv("HOSTING_TYPE") == "server" else "",
    lifespan=lifespan,
)


@app.post("/v1/jobs", status_code=status.HTTP_202_ACCEPTED)
async def submit_job(request: JobRequest) -> dict[str, str]:
    job_id = str(uuid4())
    payload = {
        "job_id": job_id,
        "records": [record.model_dump() for record in request.records],
    }
    try:
        await app.state.js.publish(
            f"inference.request.{job_id}",
            json.dumps(payload).encode(),
            headers={"Nats-Msg-Id": job_id},
        )
    except (nats.errors.ConnectionClosedError, NoRespondersError, NatsTimeoutError) as exc:
        raise HTTPException(status_code=503, detail="inference broker unavailable") from exc
    return {"job_id": job_id, "status": "pending"}


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    try:
        result_message = await app.state.js.get_last_msg(
            "INFERENCE", f"inference.result.{job_id}"
        )
    except NotFoundError:
        result_message = None
    except Exception as exc:
        raise HTTPException(status_code=503, detail="inference broker unavailable") from exc

    if result_message is not None:
        return json.loads(result_message.data)

    try:
        await app.state.js.get_last_msg("INFERENCE", f"inference.request.{job_id}")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="inference broker unavailable") from exc
    return {"job_id": job_id, "status": "pending"}
