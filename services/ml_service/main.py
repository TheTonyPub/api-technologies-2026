import pandas as pd

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.ml_service.model_loader import load_model


app = FastAPI(
    title="Anti-Fraud ML Service",
    version="1.0.0"
)

model = None
model_meta = None

FEATURES = [
    "amount",
    "avg_amount_30d",
    "tx_count_24h",
    "geo_risk",
    "merchant_risk",
    "hour"
]


class InferenceFeatures(BaseModel):
    amount: float = Field(ge=0)
    avg_amount_30d: float = Field(ge=0)
    tx_count_24h: int = Field(ge=0)
    geo_risk: float = Field(ge=0, le=1)
    merchant_risk: float = Field(ge=0, le=1)
    hour: int = Field(ge=0, le=23)


class InferenceRequest(BaseModel):
    transaction_id: str
    client_id: str
    features: InferenceFeatures


@app.on_event("startup")
def startup():
    global model, model_meta

    model, model_meta = load_model()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": model is not None
    }


@app.get("/v1/models")
def get_models():
    if model is None:
        raise HTTPException(
            status_code=500,
            detail="ML model not loaded"
        )

    return {
        "models": [
            {
                "name": model_meta["name"],
                "version": model_meta["version"],
                "status": "active"
            }
        ]
    }


@app.post("/v1/inference/check")
def check_transaction(request: InferenceRequest):
    if model is None:
        raise HTTPException(
            status_code=500,
            detail="ML model not loaded"
        )

    features = request.features.model_dump()

    data = pd.DataFrame(
        [[features[name] for name in FEATURES]],
        columns=FEATURES
    )

    score = float(model.predict_proba(data)[0][1])

    return {
        "transaction_id": request.transaction_id,
        "score": round(score, 6),
        "check_details": {
            "tool": "ML Service",
            "version": model_meta["version"],
            "action": "scoring",
            "actual_result": (
                "fraud"
                if score >= model_meta["threshold"]
                else "normal"
            )
        }
    }
