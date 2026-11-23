# Платформа данных по юридическим лицам

ДЗ 4 по кейсу СПАРК Интерфакс. Платформа хранит историю изменений компаний, обогащает её данными АБС и отдаёт актуальные карточки, состав групп и скоринг через Gateway.

## Запуск

Нужен Docker Compose 2.20 или новее. Из корня репозитория скопируйте `.env.example` в `.env` и заполните ключи команды. Укажите `MODEL_URL` или положите `company-scoring-v1.dill` в `models/`.

```sh
cp .env.example .env
docker compose up --build
```

Compose автоматически поднимает Kafka, создаёт топики и запускает Go-продьюсер. Для запуска в фоне добавьте `-d`. На Windows для копирования можно использовать `Copy-Item .env.example .env`. Для smoke выполните `bash scripts/smoke.sh`. Прогресс загрузки виден на `GET localhost:8003/status`, готовность витрины — на `GET localhost:8001/status`. Для существующего тома порядок применения миграции outbox указан в [инструкции Kafka](services/company-events/README.md#postgresql-outbox).

Порты на хосте — Gateway 8000, Enrichment 8001, Scoring 8002, Loader 8003, Client Info 8004, Group Companies 8005, ML Model 50051, PostgreSQL 5432, Redis 6379 и Kafka 29092. При запуске мониторинга Prometheus доступен на 9090, Grafana на 3000.

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

Для единой локальной проверки запусти из корня репозитория:

```powershell
python scripts/check_project.py --inn 0201141964 --monitoring
```

Скрипт проверяет HTTP-ручки, готовность данных, REST через Gateway и инфраструктуру Compose. Для мониторинга нужен запущенный `compose.monitoring.yml`. Без дополнительных флагов проверка пропускает мониторинг и выполняется без вызова `POST /sync`. Добавь `--sync`, чтобы запустить инкремент и дождаться обновления витрины, или `--http-only`, чтобы пропустить проверки через Docker. Токен берётся из `GATEWAY_TOKEN` или `.env`. Если указанного ИНН нет в витрине, передай свой через `--inn`.

Консоль показывает итог каждой проверки, `project-check.log` сохраняет HTTP-статусы, заголовки, тела ответов, длительность и вывод Docker. Код выхода `0` означает, что все запрошенные проверки прошли, `1` указывает на сбой.

`./scripts/demo.sh` выполняет сценарий проверки и пишет результаты в `demo-result.json`. Для строгой приёмки используйте чистый стенд. Сохраните вывод эталона из каталога `external-services` ветки `infra/external-services`. Начало загрузки видно в `initial_loaded_at` ответа Loader `/status`.

```sh
# В каталоге external-services, с установленными зависимостями эталона
python -m tools.expected spark --at "$CHECK_AT" --since "$INITIAL_LOADED_AT" > /path/to/expected-spark.json
# В корне проекта команды
DEMO_EXPECTED_SPARK=/path/to/expected-spark.json ./scripts/demo.sh --acceptance
```

`CHECK_AT` — момент контрольной синхронизации, `INITIAL_LOADED_AT` — начало первичной загрузки. Используйте одно окно для синхронизации и эталона. Обе даты есть в `demo-result.json` как `lastSyncAt` и `initialLoadedAt`. Выберите окно с изменениями адреса или группы, чтобы эталон сформировал `scd2_demo`. Скрипт читает `changes_since.changes` и историю `scd2_demo` прямо из JSON. Через `DEMO_HISTORY_INN` можно выбрать другую компанию из этого списка.

Строгий режим сверяет 1000 компаний, 73 группы, 451 клиента банка, новые версии и интервалы истории. В отчёт попадают карточка, время обоих запросов, повторное попадание в кэш и результаты скоринга. Если токен Gateway в `.env` отличается от `change-me`, передайте то же значение скрипту через переменную окружения `GATEWAY_TOKEN`. Для выбора сценариев используйте `DEMO_COMPANY_INN`, `DEMO_GROUP_INN` и `DEMO_SCORING_INNS` (три ИНН через пробел). Для локальной фикстуры можно задать `DEMO_EXPECTED_NEW_VERSIONS` и `DEMO_EXPECTED_HISTORY` (JSON с `inn` и массивом `versions`, у каждой версии поля `valid_from`, `valid_to`). Её счётчики переопределяются через `DEMO_EXPECTED_COMPANIES`, `DEMO_EXPECTED_GROUPS` и `DEMO_EXPECTED_BANK_CLIENTS`.

На чистом Docker-стенде с локальной копией учебных моков из `infra/external-services` загрузились 1000 компаний и 73 группы. В витрине 451 клиент банка. За окно с 18 по 19 ноября 2026 года (00:00 UTC) инкремент создал 24 версии SCD2, как в эталоне. Демо сверило интервалы истории, а `scripts/check_scoring.py` подтвердил совпадение трёх прогнозов с прямым вызовом модели.

Для контрольного прогона на сервере курса запишите фактические счётчики и время загрузки отдельно. Для проверки сбоев задайте `MOCK_SCENARIO` при запуске Loader и Enrichment через Compose. Поддерживаемые сценарии перечислены в `.env.example`.

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
