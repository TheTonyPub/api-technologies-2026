from __future__ import annotations

from typing import Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="ML Service", version="1.0.0")


class PredictRequest(BaseModel):
    model: str = Field(min_length=1, max_length=64, examples=["linear-score"])
    feature1: int = Field(ge=0, le=100, examples=[42])
    feature2: float = Field(ge=0, le=1, examples=[0.35])
    feature3: str = Field(min_length=1, max_length=32, examples=["premium"])


class ModelInfo(BaseModel):
    id: str
    description: str


class ValidationIssue(BaseModel):
    loc: List[Union[str, int]]
    msg: str
    type: str
    input: Optional[object] = None
    ctx: Optional[Dict[str, object]] = None


class ErrorResponse(BaseModel):
    detail: Union[str, List[ValidationIssue]]


MODELS = [
    ModelInfo(id="linear-score", description="Returns numeric score from all features."),
    ModelInfo(id="risk-label", description="Returns low, medium, or high from rules."),
]


@app.get("/v1/models", response_model=list[ModelInfo])
async def list_models() -> list[ModelInfo]:
    return MODELS


@app.post(
    "/v1/predict",
    responses={
        404: {"model": ErrorResponse, "description": "Model not found"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
    },
)
async def predict(payload: PredictRequest) -> dict[str, Union[str, float]]:
    if payload.model == "linear-score":
        score = round(
            payload.feature1 * 0.75
            + payload.feature2 * 20
            + len(payload.feature3) * 0.5,
            2,
        )
        return {"model": payload.model, "prediction": score}

    if payload.model == "risk-label":
        signal = payload.feature1 + payload.feature2 * 100 + len(payload.feature3) * 2
        if signal >= 120 or payload.feature3.lower().startswith("x"):
            label = "high"
        elif signal >= 65:
            label = "medium"
        else:
            label = "low"
        return {"model": payload.model, "prediction": label}

    raise HTTPException(status_code=404, detail="Model not found")
