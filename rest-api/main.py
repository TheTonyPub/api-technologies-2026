"""REST-сервис оценки риска оттока клиента.

POST   /v1/prediction                  - создать расчёт, вернуть его идентификатор
GET    /v1/prediction/{prediction_id}  - получить расчёт
PUT    /v1/prediction/{prediction_id}  - пересчитать с новыми данными
DELETE /v1/prediction/{prediction_id}  - удалить расчёт

Запуск: uvicorn main:app --reload  ->  http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# --- Модели запросов -------------------------------------------------------


class PredictionCreate(BaseModel):
    tenure_months: int = Field(ge=0, le=120, examples=[12])
    monthly_spend: float = Field(ge=0, examples=[500.0])
    support_tickets: int = Field(ge=0, le=1000, examples=[3])


# Для PUT нужны те же поля, поэтому модель одна и та же
PredictionUpdate = PredictionCreate


# --- Модели ответов --------------------------------------------------------


class PredictionCreated(BaseModel):
    prediction_id: int


class PredictionResponse(PredictionCreated):
    tenure_months: int
    monthly_spend: float
    support_tickets: int
    risk_score: float
    risk_label: str


class ErrorResponse(BaseModel):
    detail: str


app = FastAPI(title="Churn Risk Service", version="1.0.0")

# "база данных" в памяти
predictions: dict[int, PredictionResponse] = {}
next_id = 1


def calculate(data: PredictionCreate) -> PredictionResponse:
    # чем меньше стаж и больше трат и обращений, тем выше риск
    # min/max ограничивают результат диапазоном от 0 до 1
    score = min(
        1.0,
        max(
            0.0,
            0.65
            - 0.004 * data.tenure_months
            + 0.0008 * data.monthly_spend
            + 0.04 * data.support_tickets,
        ),
    )
    return PredictionResponse(
        prediction_id=0,  # настоящий id подставим при сохранении
        tenure_months=data.tenure_months,
        monthly_spend=data.monthly_spend,
        support_tickets=data.support_tickets,
        risk_score=round(score, 3),
        risk_label="high" if score >= 0.6 else "low",
    )


@app.post(
    "/v1/prediction",
    status_code=201,
    response_model=PredictionCreated,
)
async def create_prediction(payload: PredictionCreate) -> PredictionCreated:
    global next_id

    prediction = calculate(payload)
    prediction.prediction_id = next_id
    predictions[next_id] = prediction
    next_id += 1

    return PredictionCreated(prediction_id=prediction.prediction_id)


@app.get(
    "/v1/prediction/{prediction_id}",
    response_model=PredictionResponse,
    responses={404: {"model": ErrorResponse, "description": "Prediction not found"}},
)
async def get_prediction(prediction_id: int) -> PredictionResponse:
    if prediction_id not in predictions:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return predictions[prediction_id]


@app.put(
    "/v1/prediction/{prediction_id}",
    response_model=PredictionResponse,
    responses={404: {"model": ErrorResponse, "description": "Prediction not found"}},
)
async def update_prediction(prediction_id: int, payload: PredictionUpdate) -> PredictionResponse:
    if prediction_id not in predictions:
        raise HTTPException(status_code=404, detail="Prediction not found")

    prediction = calculate(payload)
    prediction.prediction_id = prediction_id
    predictions[prediction_id] = prediction

    return prediction


@app.delete(
    "/v1/prediction/{prediction_id}",
    status_code=204,
    response_model=None,
    responses={404: {"model": ErrorResponse, "description": "Prediction not found"}},
)
async def delete_prediction(prediction_id: int) -> None:
    if prediction_id not in predictions:
        raise HTTPException(status_code=404, detail="Prediction not found")

    del predictions[prediction_id]
