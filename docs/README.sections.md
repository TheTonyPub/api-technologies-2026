
---

## ДЗ 4. Реализация сервисов (кейс СПАРК)

### Запуск
```sh
cp .env.example .env        # заполнить ключи и MODEL_URL
docker compose up --build   # или: make up
```
Модель `company-scoring-v1.dill` скачивается сервисом `ml-model` по `MODEL_URL` (в git не хранится);
локально можно положить файл в `./models/`. Первичная загрузка идёт несколько минут: `make smoke` / `GET :8003/status`.
Сценарий проверки: `./scripts/demo.sh` (итоги в `demo-result.json`), сбои: `MOCK_SCENARIO=unavailable ./scripts/demo.sh`.

Сбор метрик и запуск дашборда описаны в [документации Loader](../services/loader/README.md#мониторинг).
Тесты и сборка образов запускаются в [GitHub Actions](../.github/workflows/ci.yml).
[Инструкция Kafka и Go](../services/company-events/README.md) описывает доставку событий из PostgreSQL outbox и ручную проверку отмены и повторной обработки между топиками Kafka.

### Порты
| Сервис | Порт |
|---|---|
| gateway | 8000 |
| enrichment | 8001 |
| scoring | 8002 |
| loader | 8003 |
| client-info | 8004 |
| group-companies | 8005 |
| ml-model (gRPC) | 50051 |
| postgres | 5432 (`POSTGRES_PORT`) |
| redis | 6379 (`REDIS_PORT`) |

### Участник → компонент
| Участник | Компонент |
|---|---|
| Данияр | Loader (SOAP-клиент СПАРК), инфраструктура |
| Артём | Data Store (SCD2) + Enrichment Service |
| Савелий | API Gateway + Client Info Service |
| Павел | Group Companies Service |
| Фёдор | Scoring Service + ML Model |

### Загружено записей
TODO: компаний / групп / isBankClient / версий SCD2

### Изменения архитектуры
См. [docs/CHANGES-hw4.md](docs/CHANGES-hw4.md). Договорённости между сервисами: [docs/CONTRACTS.md](docs/CONTRACTS.md). Как работаем: [docs/WORKFLOW.md](docs/WORKFLOW.md).
