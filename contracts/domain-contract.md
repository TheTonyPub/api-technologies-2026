# Профильные контракты

## COMMON error envelope

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request violates the contract",
    "details": [{"field": "horizon_days", "reason": "must be <= 30"}]
  },
  "request_id": "req-demo-001",
  "schema_version": "1.0"
}
```

## PRB

- consumer: приложение аналитика агропродовольственной сети;
- goal: создать прогноз спроса и получить результат;
- paths: `/prb/v1/forecast-jobs`, `/prb/v1/forecast-jobs/{job_id}`, `/prb/v1/forecasts/{job_id}`, `/prb/v1/events`;
- input: `product_id`, `horizon_days`, `historical_demand`, `schema_version`;
- model version: `demand-demo-2026-08`;
- long workload: 10 000 строк, 20–60 секунд в реальности; в учебном API детерминированная симуляция.

## SII

- consumer: оператор системы мониторинга посевов;
- goal: отправить признаки изображения и получить label/confidence;
- paths: `/sii/v1/inference-requests`, `/sii/v1/inference-requests/{request_id}`, `/sii/v1/inference-results/{request_id}`, `/sii/v1/stream/{request_id}`;
- input: `image_id`, `width`, `height`, `mean_intensity`, `schema_version`;
- model version: `crop-vision-demo-2026-08`;
- workload: unary request и три WebSocket update; CPU-only deterministic inference.

Значения `dependency-down` и `conflict` — синтетические sentinels для воспроизведения 503 и 409. Они не являются production identifiers.

