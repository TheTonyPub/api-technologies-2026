# Платформа данных по юридическим лицам

ДЗ 4 по кейсу СПАРК Интерфакс. Платформа хранит историю изменений компаний, обогащает её данными АБС и отдаёт актуальные карточки, состав групп и скоринг через Gateway.

## Запуск

Из корня репозитория скопируйте `.env.example` в `.env` и заполните ключи команды. Укажите `MODEL_URL` или положите `company-scoring-v1.dill` в `models/`.

```sh
cp .env.example .env
docker compose up -d --build
make smoke
```

На Windows для копирования можно использовать `Copy-Item .env.example .env`, а для smoke — `bash scripts/smoke.sh`. Прогресс загрузки виден на `GET localhost:8003/status`, готовность витрины — на `GET localhost:8001/status`. Для существующего тома порядок применения миграции outbox отдельно указан в [инструкции Kafka](services/company-events/README.md#postgresql-outbox).

Порты на хосте — Gateway 8000, Enrichment 8001, Scoring 8002, Loader 8003, Client Info 8004, Group Companies 8005, ML Model 50051, PostgreSQL 5432, Redis 6379. Дополнительные стенды публикуют Kafka на 29092, Prometheus на 9090 и Grafana на 3000.

## Архитектура

![Контекстная диаграмма](architecture/context.png)

[Исходник контекстной диаграммы](architecture/context.mmd)

![Контейнерная диаграмма](architecture/container.png)

[Исходник контейнерной диаграммы](architecture/container.mmd)

- Loader получает данные по SOAP/XML и пишет версии SCD2 в PostgreSQL. Outbox сохраняет событие об изменении вместе с новой версией.
- Enrichment проверяет ИНН в АБС пакетами по REST, собирает `company_snapshot` и обновляет карточки в Redis с TTL. При неполном ответе АБС сохраняет предыдущую витрину и запрашивает недостающие флаги повторно.
- Gateway принимает REST-запросы с Bearer-токеном. Client Info читает карточки из Redis с резервным чтением из витрины. Group Companies и Scoring читают витрину напрямую. Scoring отправляет признаки в ML Model по gRPC.
- Go-продьюсер доставляет outbox в `company.changes` с at-least-once. Go-обработчик одной транзакцией пишет в `company.audit` и фиксирует входной оффсет. Аналитический контур в объём ДЗ 4 не входит.

PostgreSQL обеспечивает согласованность истории SCD2 и outbox. Отдельная витрина ускоряет чтение, Redis управляет TTL карточек, Kafka позволяет потребителям реагировать на изменения независимо от Loader. Python позволяет переиспользовать в сервисах правила преобразования данных и формат ошибок, а в ML Model — загружать выданную модель. REST/JSON используется для прикладных API с контрактами OpenAPI, gRPC — для типизированного вызова модели по Protobuf.

Метрики длительности загрузки и инструкция по Grafana находятся в [документации Loader](services/loader/README.md#мониторинг). Сценарии запуска Kafka описаны в [документации модуля Go](services/company-events/README.md).

## Контракты

- [Gateway](contracts/api-gateway/openapi.yaml)
- [Client Info](contracts/client-info-service/openapi.yaml)
- [Group Companies](contracts/group-companies-service/openapi.yaml)
- [Scoring](contracts/scoring-service/openapi.yaml)
- [gRPC ML Model](proto/scoring.proto)

[Договорённости между сервисами](docs/CONTRACTS.md) · [Изменения относительно ДЗ 1–2](docs/CHANGES-hw4.md) · [Материалы проектирования ДЗ 2](api-design.md)

## Проверка перед сдачей

`bash scripts/demo.sh` проверяет доступные сценарии и пишет результаты в `demo-result.json`. Для строгой приёмки используйте чистый стенд, задайте `EXPECTED_CHANGES` по эталону задания и запустите:

```sh
DEMO_EXPECTED_NEW_VERSIONS="$EXPECTED_CHANGES" bash scripts/demo.sh --acceptance
```

В режиме приёмки ожидаются 1000 компаний в Loader и в витрине, 73 группы, 451 клиент банка и указанное число новых версий. Скрипт также требует историю с двумя версиями, карточку с попаданием в кэш, группу с фильтром и три разных результата скоринга. Если одного из вариантов нет среди автоматически выбранных компаний, укажите `DEMO_HISTORY_INN`, `DEMO_COMPANY_INN`, `DEMO_GROUP_INN` или `DEMO_SCORING_INNS` в окружении. Последняя переменная содержит три ИНН через пробел. Для тестовой витрины ожидаемые счётчики можно переопределить через `DEMO_EXPECTED_COMPANIES`, `DEMO_EXPECTED_GROUPS` и `DEMO_EXPECTED_BANK_CLIENTS`.

На чистом Docker-стенде с локальными SOAP/REST-фикстурами строгий прогон загрузил 1000 компаний и 73 группы, собрал витрину с 451 клиентом банка и сохранил 30 новых версий SCD2. После перезапуска стек сохранил все 1030 версий. Скоринг по трём ИНН совпал с прямым вызовом модели через `scripts/check_scoring.py`.

Для контрольного прогона на моках курса запишите фактические счётчики и время загрузки отдельно. Для проверки сбоев задайте `MOCK_SCENARIO` при запуске Loader и Enrichment через Compose. Поддерживаемые сценарии перечислены в `.env.example`.

[Чек-лист ТЗ](docs/TechSpec.md#8-что-проверить-перед-сдачей) · [Таблица соответствия](docs/README.sections.md#соответствие-требованиям) · [Тесты и сборка в GitHub Actions](.github/workflows/ci.yml)

## Команда

| Участник | Компонент |
|---|---|
| Аринов Данияр | Loader, Kafka, инфраструктура и интеграция |
| Керсуов Артём | SCD2, Enrichment и витрина |
| Ракитин Савелий | Gateway и Client Info |
| Салтыков Фёдор | Scoring и ML Model |
| Васильев Павел | Group Companies и документация |

[Порядок работы](docs/WORKFLOW.md)
