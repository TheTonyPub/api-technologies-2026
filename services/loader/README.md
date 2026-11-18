# Loader

Единственный сервис, который общается со СПАРК (SOAP). Забирает все компании и группы, пишет их в Postgres
через SCD2 (`scd2.upsert_company`, `scd2.upsert_group`), потом по расписанию подтягивает изменения.

## Как это работает

1. `SparkClient` авторизуется (`Authenticate`), `SessionId` уходит в SOAP-заголовке. При `SESSION_EXPIRED` и `AUTH_REQUIRED`
   логинится заново и повторяет запрос (один раз на вызов, при параллельных потоках логин один).
2. `get_all_inns()` проходит все страницы списка (`Page`, 100 компаний на странице; в ответе `Total` = 1000 и список в `Companies/Company`).
   Если СПАРК указал `Total`, пустая или повторная страница до получения всех записей считается ошибкой.
   Без `Total` пустая страница завершает выборку. Для списка компаний без `Total` повтор страницы также завершает выборку.
   Достижение лимита страниц без завершения выборки считается ошибкой.
3. Для каждой компании берётся краткий отчёт. Группу (`GetCompanyGroup`) запрашиваем только если в отчёте есть `GroupId`:
   так у компаний без группы нет лишнего запроса. `GroupId` берётся из отчёта, название группы и связь компании с группой
   (`Role`: parent, subsidiary, affiliate) из списка участников группы. Если группа не ответила, компания всё равно загружается.
   Если СПАРК не знает саму компанию (`COMPANY_NOT_FOUND`), запись пропускается и считается в `initial_skipped`.
4. Ответ превращается в строку таблицы (`spark_parse.to_company_row`) и проверяется (`check_row`): если нет `short_name`,
   `status` или `registration_date`, загрузка падает с понятной ошибкой, пустые версии в БД не пишутся.
5. Все запросы идут через общий лимитер (5 в секунду на процесс), потоков `LOADER_WORKERS` (по умолчанию 8).
   На каждый поток свой клиент zeep. Ошибки сети, 429/503 (с учётом `Retry-After`), `RATE_LIMIT` и прочие Fault
   повторяются с паузой 1, 2, 4, 8, 16 секунд. Ошибки в нашем запросе (`INVALID_REQUEST`, `UNKNOWN_OPERATION`) падают сразу.
6. Если часть компаний не загрузилась, остальные всё равно догружаются, потом `LoadIncomplete` со списком ИНН.
   Цикл повторит попытку и пойдёт только по недостающим (ИНН с текущей версией пропускаются).
   **valid_from версии SCD2.** В отчёте есть `ActualDate` (момент, с которого данные актуальны) и `Revision`. По умолчанию
   (`SCD2_VALID_FROM=actual`) в `scd2.upsert_company(conn, company, now)` мы передаём `now = ActualDate` компании, а не время загрузки.
   Так история совпадает с моментами изменений в СПАРК. Если эталон проверки считает иначе, ставим `SCD2_VALID_FROM=load`
   (тогда `now` это время начала загрузки). `ActualDate` и `Revision` в строку `company` не попадают, чтобы не влиять на хэш.
7. Когда всё загружено, в `load_state` пишутся `initial_loaded_at`, `last_sync_at`, `initial_versions`, `initial_skipped`,
   и последним `initial_done = true`. Время начала берётся от первого запуска и после падения не сдвигается.
8. Дальше раз в `INCREMENTAL_INTERVAL_SEC` (300 с): `GetChangedCompanies(Since=last_sync_at)` (тоже постраничный: `Total` это число изменений, у одной
   компании их может быть несколько), перезагрузка только изменённых компаний. В списке изменений для каждого ИНН есть `ChangedAt` и `ChangeType`
   (`head`, `address`, `okved`, `status`, `group`).
   `last_sync_at` хранит время начала запроса. Он сохраняет прежнее значение при неполной выборке, повторной странице
   или сбое обработки. `changed_inns` хранит до 100 ИНН с недавно записанными версиями.

## HTTP

- `GET /health`
- `GET /metrics`: метрики Prometheus. Доступны и в режиме dry-run.
- `GET /status`: `initial_done`, `initial_loaded_at`, `initial_versions`, `initial_skipped`, `last_sync_at`, `changed_inns`,
  `progress` (`total`, `done`, `skipped`, `failed`, `failed_sample`), `last_error`, `companies`, `versions`, `groups`, `dry_run`.
- `POST /sync`: запустить инкремент сейчас. Ответ: `changed`, `created` (новые версии SCD2), `since`, `last_sync_at` и счётчики.
  Если первичная загрузка не закончена: 409. Если инкремент упал: 503. Формат ошибок: `code`, `message`, `traceId`.

## Переменные окружения

| Переменная | Значение |
|---|---|
| `SPARK_URL`, `SPARK_WSDL`, `SPARK_LOGIN`, `SPARK_PASSWORD` | доступ к СПАРК (логин и пароль из `.env`) |
| `SPARK_NS` | namespace SOAP-заголовка; пусто = взять из WSDL |
| `MOCK_SCENARIO` | `slow`, `timeout`, `error`, `unavailable`, `ratelimit`; пусто = заголовок не отправляется |
| `RATE_LIMIT_RPS` | запросов в секунду, по умолчанию 5; при частых 429 поставить 4 |
| `LOADER_WORKERS` | потоков, по умолчанию 8 |
| `SCD2_VALID_FROM` | `actual` (по умолчанию): `valid_from` = `ActualDate` из отчёта; `load`: время загрузки |
| `SPARK_PAGE_SIZE` | `PageSize` для списков; 0 = не передавать (сервер отдаёт по 100) |
| `INCREMENTAL_INTERVAL_SEC` | период инкремента, по умолчанию 300 |
| `LOADER_DRY_RUN` | `true`: в БД не пишем, данные только в памяти |

## Первый запуск против настоящего мока

1. Сверить имена операций и параметров с WSDL и увидеть реальные ответы:

   ```sh
   pip install zeep requests
   python scripts/spark_probe.py
   ```

   Если какое-то имя в WSDL другое, поправить константы `OP_*`, `P_*` вверху `soap_client.py`.
   Если вывод разбора показывает пустые поля, добавить нужные имена в `pick(...)` в `spark_parse.py`.

2. Проверить всю загрузку без записи в БД (пока нет `scd2.py`):

   ```sh
   LOADER_DRY_RUN=true docker compose up -d --build loader
   docker compose logs -f --tail=30 loader
   curl localhost:8003/status
   ```

   Ожидаем `companies: 1000`, `groups: 73`, `progress.failed: 0`, `initial_done: true`.
   Загрузка идёт 5-7 минут: 1000 отчётов плюс группы (только у компаний с `GroupId`), при лимите 5 запросов в секунду.

3. Боевой режим: убрать `LOADER_DRY_RUN`, дождаться `scd2.py` Артёма.

## Тесты

```sh
python -m pip install -r services/loader/requirements.txt
python scripts/dev.py test
```

Модульные тесты используют подставной SOAP-сервис и хранилище в памяти. Чтобы проверить PgStore
на PostgreSQL, задай `LOADER_TEST_DATABASE_URL` с доступом на создание схем в тестовой базе.
Каждый тест создаёт собственную схему, применяет миграцию и удаляет эту схему после проверки.
GitHub Actions применяет миграции к тестовой базе, запускает тесты Loader, SCD2 и Enrichment
на Python 3.11 с PostgreSQL 16 и Redis, проверяет Compose и собирает образы обоих сервисов.

## Мониторинг

С готовым `.env` подними Loader, Prometheus и Grafana из корня репозитория.

```sh
docker compose -f docker-compose.yml -f compose.monitoring.yml up -d --build loader prometheus grafana
```

Для проверки до готовности SCD2 выставь `LOADER_DRY_RUN=true` в `.env`. Метрики Loader доступны
на [localhost:8003/metrics](http://localhost:8003/metrics), сбор метрик виден в [Prometheus](http://localhost:9090/targets).
Открой дашборд [СПАРК · Loader](http://localhost:3000/d/spark-loader) в Grafana.
При первом запуске Grafana использует стандартный вход `admin` / `admin` и предлагает сменить пароль.

Дашборд показывает доступность Loader, время с последнего успешного инкремента, результаты запусков и обработки
компаний, p95 времени обработки одной компании и повторы SOAP-запросов. p95 отсчитывается от начала работы
потока и включает ожидание лимитера, запросы СПАРК и запись. Возраст инкремента появится после первого
успешного инкремента текущего процесса.
