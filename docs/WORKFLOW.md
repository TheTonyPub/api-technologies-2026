# Как работаем (ДЗ 4, кейс СПАРК)

## Кто за что отвечает (предложение — подтвердить в чате)
| Участник | Компонент | Папки/файлы |
|---|---|---|
| Данияр | Loader (SOAP-клиент), инфраструктура | `services/loader/` (кроме `scd2.py`), `docker-compose.yml`, `scripts/`, `Makefile` |
| Артём | Store (SCD2) + Enrichment | `services/loader/app/scd2.py`, `db/migrations/`, `services/enrichment/` |
| Савелий | API Gateway + Client Info | `services/gateway/`, `services/client-info/` |
| Павел | Group Companies (+ README, диаграммы, документы) | `services/group-companies/`, `README.md`, `architecture/`, `docs/` |
| Фёдор | Scoring + ML Model | `services/scoring/`, `services/ml-model/`, `proto/` |

Общие файлы — только через PR с одобрением тимлида и сообщением в чат:
`libs/common/`, `docs/CONTRACTS.md`, `.env.example`, `.gitattributes`, `.gitignore`.
Участник без собственного кода получает не больше 60% баллов команды, поэтому у каждого свои коммиты в свой компонент.

## Правила
- Ветки `feat/<кто>-<что>` от `homework/04-api-services`, мелкие PR, осмысленные коммиты (не «fix»).
- Схема БД: новые файлы `db/migrations/00N_*.sql`. На существующем томе применяем новую миграцию отдельно. `make reset` нужен для чистого стенда, данные этого стенда будут удалены.
- Ключи и пароли только в локальном `.env`. Если ключ попал в коммит — сразу сказать, его придётся перевыпускать.
- Ошибки REST — единый формат `{code, message, traceId}` через `platform_common.errors` (см. примеры в сервисах).
- Исходящие вызовы моков: `X-Mock-Scenario` только если `MOCK_SCENARIO` не пуст.

## Быстрый старт (один раз)
```sh
cp .env.example .env                      # заполнить ключи (TEAM_API_KEY, SPARK_LOGIN, SPARK_PASSWORD, MODEL_URL)
pip install -r services/<свой-сервис>/requirements.txt
```
Модель `company-scoring-v1.dill` положить в `./models/` (в git не коммитить).

## Работа над СВОИМ сервисом (без пересборки всего compose)
```sh
make db                                   # поднять только Postgres и Redis
python scripts/dev.py local-env           # .env.local: localhost вместо имён контейнеров
python scripts/dev.py proto               # только Scoring и ML Model: gRPC-заглушки в .gen/
python scripts/dev.py gateway             # или enrichment | scoring | loader | client-info | group-companies | ml-model
```
Сервис стартует с `--reload` на своём порту. Соседние сервисы — тоже на хосте (`localhost:800x`) или в docker.
Если `make` нет (Windows) — запускайте команды `python scripts/dev.py ...` и `docker compose ...` напрямую.

## Полный запуск
`docker compose up --build` (или `make up`). Прогресс загрузки: `make smoke` / `GET :8003/status`.
Чистый старт: `make reset` (удалит данные БД).

## Тесты
`python scripts/dev.py test` запускает общие тесты Python, Scoring, Loader и API. Для проверок PostgreSQL задайте тестовые DSN. CI применяет миграции, запускает этот набор, тесты Enrichment и проверки Go.

## Порты
gateway 8000 · enrichment 8001 · scoring 8002 · loader 8003 · client-info 8004 · group-companies 8005 · ml-model (gRPC) 50051 · postgres 5432 · redis 6379
