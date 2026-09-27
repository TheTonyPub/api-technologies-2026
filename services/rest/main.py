import os

from fastapi import FastAPI
from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    tenure_months: int = Field(ge=0, le=120)
    monthly_spend: float = Field(ge=0)
    support_tickets: int = Field(ge=0)


class PredictionResponse(BaseModel):
    risk_score: float
    risk_label: str


app = FastAPI(
    title="Seminar 04 REST inference",
    root_path="/rest" if os.getenv("HOSTING_TYPE") == "server" else "",
)


@app.post("/v1/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest) -> PredictionResponse:
    # A simple deterministic score, intentionally easy to calculate by hand.
    score = min(
        1.0,
        max(
            0.0,
            0.65
            - 0.004 * request.tenure_months
            + 0.0008 * request.monthly_spend
            + 0.04 * request.support_tickets,
        ),
    )
    return PredictionResponse(
        risk_score=round(score, 3),
        risk_label="high" if score >= 0.6 else "low",
    )
