import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError, Field


class Telemetry(BaseModel):
    temperature: float = Field(ge=-50, le=200)
    vibration: float = Field(ge=0)
    rpm: float = Field(ge=0, le=50000)


app = FastAPI(
    title="Seminar 04 WebSocket inference",
    root_path="/stream" if os.getenv("HOSTING_TYPE") == "server" else "",
)


@app.websocket("/v1/live")
async def live_predictions(socket: WebSocket) -> None:
    await socket.accept()
    try:
        while True:
            try:
                payload = await socket.receive_json()
                telemetry = Telemetry.model_validate(payload)
            except (ValidationError, TypeError, ValueError) as exc:
                await socket.send_json({"error": "invalid_telemetry", "detail": str(exc)})
                continue

            score = min(
                1.0,
                max(
                    0.0,
                    max(0.0, telemetry.temperature - 70.0) / 80.0
                    + telemetry.vibration / 10.0
                    + max(0.0, telemetry.rpm - 3000.0) / 20000.0,
                ),
            )
            await socket.send_json(
                {"anomaly_score": round(score, 3), "anomaly": score >= 0.5}
            )
    except WebSocketDisconnect:
        return
