# Сервисы ДЗ 4 и локальный запуск

Инструкция для ветки `homework/04-api-services`. Команды рассчитаны на PowerShell и выполняются из корня репозитория. Для полного прогона нужны доступы к учебным СПАРК и АБС и файл модели. Kafka, чтение тестовых карточек и автоматические тесты можно проверить отдельно.

## Карта сервисов

```mermaid
flowchart LR
    SPARK[СПАРК] -->|SOAP/XML| L[Loader]
    L --> PG[(PostgreSQL)]
    PG --> E[Enrichment]
    E -->|REST lookup| ABS[АБС]
    E -->|Витрина| PG
    E -->|Карточки| R[(Redis)]
    U[Клиент] --> G[Gateway]
    G --> C[Client Info]
    G --> GC[Group Companies]
    G --> S[Scoring]
    R --> C
    PG --> C
    PG --> GC
    PG --> S
    S -->|gRPC| M[ML Model]
    PG -->|Outbox| P[Go Publisher]
    P --> KC[company.changes]
    KC --> PR[Go Processor]
    PR --> KA[company.audit]
```

| Сервис | Порт на хосте | Что делает | Точка входа |
| --- | --- | --- | --- |
| Loader | `127.0.0.1:8003` | Авторизуется в СПАРК, загружает список и отчёты, пишет историю и курсор в PostgreSQL. | [main.py](../services/loader/app/main.py) |
| Enrichment | `8001` | Проверяет ИНН в АБС, пересобирает витрину и прогревает Redis. Отдаёт историю компании. | [pipeline.py](../services/enrichment/app/pipeline.py) |
| Gateway | `8000` | Валидирует ИНН юрлица из 10 цифр и Bearer-токен. Маршрутизирует три REST-запроса, передаёт `X-Request-Id` и `X-Cache`. | [main.py](../services/gateway/app/main.py) |
| Client Info | `8004` | Читает `company:{inn}` из Redis. При промахе или сбое Redis читает `company_snapshot` и пытается заполнить кэш. | [repository.py](../services/client-info/app/repository.py) |
| Group Companies | `8005` | Возвращает участников группы, включая запрошенную компанию. `onlyBankClients=true` фильтрует участников и меняет `totalMembers`. Компания без группы получает пустой список. | [main.py](../services/group-companies/app/main.py) |
| Scoring | `8002` | Читает компанию и группу из витрины, считает признаки, вызывает `Predict`. Отдаёт `probability`, `modelVersion`, `scoredAt` и `dataAsOf`. | [main.py](../services/scoring/app/main.py) |
| ML Model | `50051` | Загружает `.dill`, строит DataFrame в порядке признаков из `meta.features` и возвращает вероятность класса 1. gRPC-методы `GetInfo` и `Predict`. | [server.py](../services/ml-model/app/server.py) |
| Event Publisher | — | Читает PostgreSQL outbox, публикует `CompanyChanged` в Kafka и отмечает доставленные строки. Стартует в основном Compose. | [main.go](../services/company-events/cmd/publisher/main.go) |
| Event Processor | — | За один ручной запуск переносит одну входную запись в `company.audit`, фиксируя её вместе с оффсетом группы внутри Kafka. | [main.go](../services/company-events/cmd/processor/main.go) |

PostgreSQL 16 слушает порт `5432`, Redis 7 — `6379`, Kafka — `127.0.0.1:29092`. В контейнерах используются имена `postgres:5432`, `redis:6379`, `kafka:9092` и `ml-model:50051`. Kafka работает в KRaft на одном брокере. Сервис инициализации `kafka-topics` создаёт `company.changes` и `company.audit` и штатно выходит с кодом 0. [Compose](../docker-compose.yml) · [Kafka Compose](../compose.kafka.yml)

### Как обновляются данные

1. Loader вызывает `Authenticate` и постраничный `GetCompanyList`. Для каждого ИНН берёт `GetCompanyShortReport`, а при наличии группы запрашивает `GetCompanyGroup`. По умолчанию восемь потоков делят лимит в пять SOAP-запросов в секунду. Loader повторяет временные сбои и может продолжить первичную загрузку с пропущенных ИНН. [SOAP-клиент](../services/loader/app/soap_client.py) · [Loader](../services/loader/app/loader.py)
2. Loader записывает историю SCD2 в `company_versions` и данные групп в `company_groups`. При изменении бизнес-полей закрывает старую версию и открывает новую. По умолчанию `valid_from` берётся из `ActualDate` СПАРК. Новая версия уже известной компании и строка `company_outbox` сохраняются одной транзакцией. Первичная версия и повтор идентичного отчёта события не создают. [SCD2](../services/loader/app/scd2.py) · [Миграции](../db/migrations)
3. После `load_state.initial_done=true` Loader вызывает `GetChangedCompanies` каждые 300 секунд по умолчанию. Курсор `last_sync_at` равен времени начала успешной синхронизации. При неполном проходе он остаётся прежним. `POST /sync` запускает тот же инкремент вручную. [Инкремент](../services/loader/app/incremental.py)
4. Enrichment опрашивает состояние Loader каждые пять секунд по умолчанию. Когда курсор меняется, проверяет в АБС все актуальные ИНН батчами по 500 через `POST /v1/legal-clients:lookup` и сохраняет флаги в `bank_clients`. Если часть флагов отсутствует, сохраняет прежнюю витрину и повторяет запрос для недостающих ИНН. После полного ответа собирает `company_snapshot` и публикует карточки с TTL `CACHE_TTL_SECONDS` (3600 секунд по умолчанию). [Enrichment](../services/enrichment/app/pipeline.py)
5. Scoring передаёт модели пять признаков. Возраст считается в полных месяцах, ОКВЭД и статус передаются строками, размер группы включает саму компанию, а число клиентов банка в группе исключает её. `SCORING_AS_OF=today` считает возраст на текущую дату UTC, `data_as_of` — на дату витрины. [Признаки](../services/scoring/app/features.py) · [gRPC-контракт](../proto/scoring.proto)

Publisher берёт необработанные строки по `version_id` и держит блокировку до подтверждения Kafka и коммита PostgreSQL. Ключ Kafka — ИНН. JSON содержит `event_id`, `version_id`, `inn`, `occurred_at` и `type`. Если Kafka подтвердила запись, а PostgreSQL не сохранил `published_at`, возможен повтор с тем же `event_id` (at-least-once). Processor использует группу `company-audit-dev`, читает в режиме `read_committed` и атомарно сохраняет audit-запись и входной оффсет. Его гарантия распространяется на обработку каждой входной записи Kafka. Две входные записи с одинаковым `event_id` образуют две записи аудита. [Kafka и outbox](../services/company-events/README.md)

## Полный запуск

### 1. Подготовить окружение

Запусти Docker Desktop в режиме Linux-контейнеров. В корне репозитория проверь доступ к Engine и создай конфиг, если файла ещё нет.

```powershell
Set-Location C:\APIgroup\api-technologies-2026
docker version
docker compose version
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

В `.env` заполни `SPARK_LOGIN` и `SPARK_PASSWORD` для SOAP, `TEAM_API_KEY` для АБС и `GATEWAY_TOKEN` для HTTP. Адреса мока уже есть в [.env.example](../.env.example). Оставь `LOADER_DRY_RUN=false` для записи в БД. Если меняешь реквизиты PostgreSQL, согласуй `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` и `DATABASE_URL`.

Положи выданный команде `company-scoring-v1.dill` в `models/` или укажи `MODEL_URL`. Сервис скачает файл в каталог модели при старте. `MODEL_TOKEN` нужен для URL с Bearer-авторизацией, `MODEL_SHA256` включает проверку контрольной суммы. `MODEL_PATH` в Compose указывает на путь внутри контейнера. [Загрузка модели](../services/ml-model/app/model_store.py)

### 2. Поднять контейнеры

На пустом томе PostgreSQL автоматически применит `001_init.sql` и `002_company_outbox.sql`. Если том уже существует, проверь наличие outbox перед запуском Loader и Publisher.

```powershell
docker compose up -d --wait postgres
"SELECT to_regclass('public.company_outbox');" |
  docker compose exec -T postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'
```

Если результат пустой, примени миграцию к существующему тому.

```powershell
docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB -f /docker-entrypoint-initdb.d/002_company_outbox.sql'
```

Затем проверь конфигурацию и запусти сервисы.

```powershell
docker compose -f docker-compose.yml -f compose.monitoring.yml config --quiet
docker compose up -d --build
docker compose ps -a
```

Если модель ещё не получена, подними цепочку загрузки данных и Kafka отдельной командой:

```powershell
docker compose up -d --build loader enrichment client-info group-companies event-publisher
```

Полный Compose ждёт `ml-model` перед запуском Scoring, а Gateway ждёт Scoring. После добавления модели выполни `docker compose up -d --build` ещё раз. Проверяй `docker compose logs --tail=100 ml-model scoring gateway`, если цепочка не стартует.

### 3. Дождаться загрузки и витрины

```powershell
docker compose logs --tail=50 loader enrichment event-publisher
Invoke-RestMethod http://localhost:8003/status
Invoke-RestMethod http://localhost:8001/status
```

У Loader проверь `initial_done=true` и `last_error`. На учебном наборе ожидаются 1000 компаний и 73 группы. Первичная загрузка может занять несколько минут. У Enrichment проверь `ready=true`, 1000 строк витрины и 451 клиента банка. После ручной синхронизации дождись, чтобы `last_sync_at` Enrichment догнал маркер Loader. `/health` проверяет доступность HTTP-процесса. Для проверки данных используй `/status`.

### 4. Проверить HTTP и gRPC

Подставь значение `GATEWAY_TOKEN` из своего `.env`. Для карточки возьми ИНН из витрины, для проверки фильтра возьми компанию с `group_id`.

```powershell
docker compose exec -T postgres psql -U spark -d spark -c "SELECT inn, group_id, is_bank_client FROM company_snapshot WHERE group_id IS NOT NULL ORDER BY inn LIMIT 5;"
$inn = '0201141964'
$token = 'change-me' # замени, если в .env другое значение
$api = 'http://localhost:8000'
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/$inn"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/$inn"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/$inn/group"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/$inn/group?onlyBankClients=true"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/$inn/scoring"
curl.exe -i "$api/v1/companies/$inn"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/abc"
curl.exe -i -H "Authorization: Bearer $token" "$api/v1/companies/0000000000"
```

Ожидай `200` для существующей компании, `X-Cache: HIT` при повторном чтении карточки, в отфильтрованной группе — только `isBankClient=true`. Без токена ожидай `401`, с неверным форматом ИНН — `400`, с отсутствующим ИНН — `404 COMPANY_NOT_FOUND`. Ошибки Gateway имеют поля `code`, `message`, `traceId` и иногда `details`. Недоступность нижестоящего сервиса даёт `503`, таймаут — `504`. По умолчанию `UPSTREAM_TIMEOUT_SEC=0.9` у Gateway и `ML_TIMEOUT_SEC=0.6` у Scoring. Для прямой проверки GET-запросы с теми же путями доступны на портах 8004, 8005 и 8002 соответственно. [REST-контракты](../contracts) · [Соглашения сервисов](CONTRACTS.md)

Проверка gRPC из контейнера Scoring использует сгенерированный клиент и адрес из его окружения:

```powershell
docker compose exec -T scoring python -c "import grpc, os, scoring_pb2 as pb, scoring_pb2_grpc as rpc; print(rpc.CompanyScoringStub(grpc.insecure_channel(os.environ['ML_MODEL_ADDR'])).GetInfo(pb.InfoRequest(), timeout=3))"
```

### 5. Проверить инкремент и Kafka

```powershell
Invoke-RestMethod -Method Post http://localhost:8003/sync
Invoke-RestMethod "http://localhost:8001/v1/internal/companies/$inn/history"
docker compose exec -T postgres psql -U spark -d spark -c "SELECT event_id, version_id, inn, published_at FROM company_outbox ORDER BY version_id DESC LIMIT 5;"
docker compose logs --tail=50 event-publisher
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list
```

`created=0` — нормальный результат, если в окне отсутствуют новые версии. При `created>0` подставь ИНН из `changed_inns` в запрос истории. Проверь интервалы `validFrom` и `validTo`, единственную текущую версию, `changedFields` и заполнение `published_at`. Для просмотра событий:

```powershell
docker compose exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic company.changes --from-beginning --property print.key=true --timeout-ms 5000
```

Чтобы воспроизвести Kafka-транзакцию без изменений в СПАРК, понадобится Go 1.24+. [Отдельное Kafka-демо](../services/company-events/README.md#отдельный-стенд-для-ручной-демонстрации) использует порт `39092` и синтетическое событие. После запуска с `KAFKA_DEMO_ABORT=1` запись видна в `company.changes`, а audit-consumer с `read_committed` её не видит. После обычного запуска Processor обрабатывает тот же оффсет, и в аудите появляется одна запись.

### 6. Мониторинг и остановка

```powershell
docker compose -f docker-compose.yml -f compose.monitoring.yml up -d prometheus grafana
curl.exe -fsS http://localhost:8003/metrics
```

Состояние сборщика видно в Prometheus на `localhost:9090/targets`. В Grafana на `localhost:3000/d/spark-loader` есть длительность загрузки, ошибки, повторы SOAP и p95 обработки. Для первого входа используется `admin/admin`, если настройки Grafana ещё не менялись. `down` сохраняет тома. `down -v` или `make reset` удаляют данные стенда, включая историю PostgreSQL и топики Kafka.

```powershell
docker compose -f docker-compose.yml -f compose.monitoring.yml down
```

## Проверка без доступа к СПАРК и АБС

На пустом стенде можно залить восемь синтетических строк в `company_snapshot` и проверить читающие REST-сервисы. Команды используют дефолтные реквизиты PostgreSQL и стандартные порты. Выполняй их на стенде для фикстуры, пока порты `8000`, `8002`, `8004`, `8005`, `5432` и `6379` свободны.

```powershell
docker compose -p api-fixture up -d --wait postgres redis
$OutputEncoding = [Text.UTF8Encoding]::new($false)
Get-Content -Raw -Encoding utf8 db/dev/seed_snapshot.sql |
  docker compose -p api-fixture exec -T postgres psql -v ON_ERROR_STOP=1 -U spark -d spark
docker compose -p api-fixture up -d --build --no-deps client-info group-companies scoring gateway
```

Через Gateway проверь карточку `9990000001` и группу. Из четырёх участников этой группы двое — клиенты банка. У `9990000011` фильтр по клиентам банка вернёт пустой список, у `9990000021` нет группы. Карточка при первом запросе на пустом Redis даст `MISS`, при втором — `HIT`. Без запущенной модели скоринг существующего ИНН вернёт `503 SERVICE_UNAVAILABLE` или `504 UPSTREAM_TIMEOUT`, если сработает таймаут. [Фикстура](../db/dev/seed_snapshot.sql)

```powershell
docker compose -p api-fixture down
```

## Автоматические тесты и приёмка

### Python и Go

Понадобятся Python 3.11 и Go 1.24+. Открой отдельный PowerShell для тестовых переменных окружения. Для интеграционных тестов ниже поднимаются отдельные PostgreSQL и Redis на портах 15432 и 16379. Тесты Enrichment пересобирают витрину и меняют тестовые ключи Redis.

```powershell
python -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r services/loader/requirements.txt -r services/enrichment/requirements.txt -r services/gateway/requirements.txt -r services/group-companies/requirements.txt -r services/client-info/requirements.txt pytest ruff==0.15.12

$migrations = (Resolve-Path db/migrations).Path
docker run -d --rm --name api-test-pg -p 127.0.0.1:15432:5432 -e POSTGRES_USER=spark -e POSTGRES_PASSWORD=spark -e POSTGRES_DB=spark --mount "type=bind,source=$migrations,target=/docker-entrypoint-initdb.d,readonly" postgres:16
docker run -d --rm --name api-test-redis -p 127.0.0.1:16379:6379 redis:7-alpine
docker exec api-test-pg pg_isready -h 127.0.0.1 -U spark -d spark
docker exec api-test-redis redis-cli ping
```

Дождись `accepting connections` и `PONG`, затем выполни:

```powershell
$env:DATABASE_URL = 'postgresql://spark:spark@127.0.0.1:15432/spark'
$env:LOADER_TEST_DATABASE_URL = $env:DATABASE_URL
$env:TEST_DATABASE_URL = $env:DATABASE_URL
$env:REDIS_URL = 'redis://127.0.0.1:16379/0'
$env:ABS_URL = 'http://127.0.0.1:1/abs'
$env:TEAM_API_KEY = 'test'
& $py -m ruff check --select E9,F63,F7,F82 libs services scripts
& $py scripts/dev.py test
$env:PYTHONPATH = 'services/enrichment;libs/common'
& $py -m pytest -q -rs services/enrichment/tests
go -C services/company-events test ./...
go -C services/company-events vet ./...
docker stop api-test-pg api-test-redis
Remove-Item Env:DATABASE_URL,Env:LOADER_TEST_DATABASE_URL,Env:TEST_DATABASE_URL,Env:REDIS_URL,Env:ABS_URL,Env:TEAM_API_KEY,Env:PYTHONPATH
```

`dev.py test` запускает Loader, SCD2, общее преобразование данных, признаки Scoring, проверки Gateway с Client Info и Group Companies. Enrichment запускается отдельной командой pytest. У Go сейчас нет файлов `_test.go`, поэтому `go test` проверяет сборку пакетов, а доставку и транзакцию проверяют отдельные сценарии Kafka. [CI](../.github/workflows/ci.yml)

### Сквозное демо

В Git Bash или WSL при доступе к портам стенда выполни:

```bash
bash scripts/smoke.sh
export GATEWAY_TOKEN=change-me  # подставь значение из .env
export DEMO_COMPANY_INN=0201141964
export DEMO_GROUP_INN=0201141964
export DEMO_SCORING_INNS="0201141964 0201419137 0204853543"
bash scripts/demo.sh
```

Если примеров нет в твоём наборе данных, подставь реальные ИНН из витрины. Smoke проверяет HTTP `/health` на портах 8000–8005 и запрашивает статус Loader. Demo сам вызывает `POST /sync`, ждёт витрину и пишет `demo-result.json`. Для строгой приёмки подай `DEMO_EXPECTED_SPARK=/path/to/expected-spark.json` и запусти `bash scripts/demo.sh --acceptance`. Сгенерируй эталон командой `python -m tools.expected spark --at "$CHECK_AT" --since "$INITIAL_LOADED_AT"` в каталоге `external-services` из ветки `infra/external-services`. Используй одинаковое окно синхронизации и эталона с изменением адреса или группы. [Приёмка в README](../README.md#проверка-перед-сдачей)

Чтобы сверить оценки Gateway с прямым вызовом того же файла модели, установи зависимости ML и передай те же настройки `GATEWAY_TOKEN`, `SCORING_AS_OF` и хостовый `DATABASE_URL`, если они отличаются от стандартных. Затем укажи три ИНН из витрины.

```powershell
& $py -m pip install -r services/ml-model/requirements.txt "psycopg[binary]"
& $py scripts/check_scoring.py $inn1 $inn2 $inn3
```

### Запуск одного сервиса на хосте

```powershell
docker compose up -d postgres redis
& $py -m pip install -r services/scoring/requirements.txt
& $py scripts/dev.py local-env
& $py scripts/dev.py proto
& $py scripts/dev.py scoring
```

`local-env` делает `.env.local` с адресами `localhost`, а `proto` пишет Python-заглушки в `.gen/`. Для другого сервиса установи его `requirements.txt` и передай его имя в `dev.py`. Зависимости должны быть доступны по адресам из `.env.local`, а порт сервиса на хосте должен быть свободен. [Помощник запуска](../scripts/dev.py)

## Типовые сбои

| Симптом | Что проверить |
| --- | --- |
| `ml-model` постоянно перезапускается | `docker compose logs ml-model`. Проверь наличие `models/company-scoring-v1.dill` или `MODEL_URL`, токен скачивания и SHA-256. |
| Loader жив, `initial_done=false` | Смотри `progress`, `last_error` и логи. При частых 429 можно снизить `RATE_LIMIT_RPS` до 4. Изменения из `.env` подхватятся после `docker compose up -d loader`. |
| Enrichment жив, `ready=false` | Дождись первичной загрузки, проверь `TEAM_API_KEY`, `ABS_URL` и `last_error`. Для имитации сбоя на учебном моке доступны `MOCK_SCENARIO=slow|timeout|error|unavailable|ratelimit`. |
| Publisher пишет `relation "company_outbox" does not exist` | Примени `002_company_outbox.sql` к существующему тому по шагу 2. |
| Kafka consumer завершился по timeout | При проверке через `--timeout-ms` таймаут отмечает конец ожидания. Проверь число полученных сообщений и нужный `event_id`. |
