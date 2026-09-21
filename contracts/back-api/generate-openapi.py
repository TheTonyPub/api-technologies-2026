import os
import yaml
from enum import IntEnum
from fastapi import FastAPI
from pydantic import BaseModel, Field

#поднимаем фастапи 
app = FastAPI(
    title="Back API / Точка входа",
    description="Принимает транзакцию от АБС, проверяет на фрод и отдает вердикт.",
    version="1.0.0",
    openapi_version="3.1.0"
)

#модельки данных

class VerdictEnum(IntEnum):
    OK = 0      #норм транзакция
    FRAUD = 1   # фрод (отклонить!!!!!!!!!)

class TransactionRequest(BaseModel):
    transaction_id: str = Field(..., description="ID транзакции из АБС", example="tx-777")
    account_id: str = Field(..., description="Чей счет", example="acc-12345")
    amount: float = Field(..., gt=0, description="Сумма (должна быть > 0)", example=5000.0)
    currency: str = Field("RUB", description="Валюта", example="RUB")
    timestamp: str = Field(..., description="Время отправки", example="2026-09-21T10:00:00Z")

class TransactionVerdictResponse(BaseModel):
    transaction_id: str = Field(..., description="ID транзакции")
    verdict: VerdictEnum = Field(..., description="0 - Одобрено, 1 - Фрод")
    evaluated_at: str = Field(..., description="Время вынесения вердикта")

class ErrorResponse(BaseModel):
    code: str = Field(..., description="Код ошибки", example="BAD_REQUEST")
    message: str = Field(..., description="Что пошло не так", example="Неверная сумма")


#эндопоинты

@app.post(
    "/v1/transactions/evaluate",
    response_model=TransactionVerdictResponse,
    summary="Проверить транзакцию на фрод",
    responses={
        200: {"model": TransactionVerdictResponse, "description": "Всё ок, вердикт готов"},
        400: {"model": ErrorResponse, "description": "АБС прислала битые данные"},
        404: {"model": ErrorResponse, "description": "Эндпоинт не найден"},
        422: {"model": ErrorResponse, "description": "Ошибка валидации (например, отрицательная сумма)"},
        500: {"model": ErrorResponse, "description": "Сервер упал / ошибка бэка"}
    }
)
def evaluate_transaction(req: TransactionRequest):
    #тут просто заглушка для генерации схемы
    pass


#генерация ямл

def make_yaml():
    schema = app.openapi()
    
    #сохраняем по красоте в папку контрактов
    out_dir = os.path.join("contracts", "back-api")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "openapi.yaml")
    
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, allow_unicode=True, sort_keys=False)
        
    print("Готово! Контракт записан в contracts/back-api/openapi.yaml")

if __name__ == "__main__":
    make_yaml()