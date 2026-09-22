# Семинар 3: взаимодействие API

Три независимых FastAPI-сервиса: валидация ML-запросов, SQLite и защищённая
фоновая обработка CSV.

## Запуск

```sh
cp .env.example .env
docker compose up --build
```

Swagger: [ML Service](http://localhost:8001/docs),
[User Service](http://localhost:8002/docs),
[CSV Processor](http://localhost:8003/docs).

## ML Service — 8001

- `GET /v1/models`: `linear-score`, `risk-label`.
- `POST /v1/predict`: `model`, `feature1` — целое `0..100`, `feature2` —
  число `0..1`, `feature3` — строка длиной `1..32`.
- `linear-score` возвращает число. `risk-label` возвращает `low`, `medium` или
  `high`; одинаковые признаки дают детерминированные, но различающиеся ответы.
- Неизвестная модель: 404. Невалидные признаки: 422.

```sh
curl -X POST http://localhost:8001/v1/predict \
  -H 'content-type: application/json' \
  -d '{"model":"linear-score","feature1":42,"feature2":0.35,"feature3":"premium"}'
```

## User Service — 8002

- `POST /v1/user`: `age` `6..90`, `sex` `male|female`; 201 и `user_id`.
- `PUT /v1/user/{user_id}` обновляет один или оба поля; 201.
- Отсутствующий пользователь: 404. Пустой или невалидный payload: 422.
- SQLite хранится в Docker volume `user-data`.

## CSV Processor — 8003

`PROCESSING_TOKEN` хранится в локальном `.env`.

- `GET /v1/example`: CSV без авторизации.
- `POST /v1/process`: Bearer token, `text/csv`, 202 и UUID `run_id`.
- Ровно `feature1,feature2,feature3`; первые две колонки числовые, максимум
  100 строк.
- Фоновая задача ждёт секунду, прибавляет 10 к числам, оставляет первый символ
  текста.
- `GET /v1/data/{run_id}` с Bearer token выдаёт CSV один раз; до готовности и
  после выдачи возвращает 404.

```sh
TOKEN=$(sed -n 's/^PROCESSING_TOKEN=//p' .env)
curl -X POST http://localhost:8003/v1/process \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: text/csv' \
  --data-binary $'feature1,feature2,feature3\n1,2.5,hello\n'
```
