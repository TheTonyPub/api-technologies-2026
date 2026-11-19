# Договорённости между сервисами

REST-контракты сервисов находятся в `contracts/`. Действующий контракт ML Model находится в `proto/scoring.proto`. Изменения относительно ДЗ 1–2 описаны в `docs/CHANGES-hw4.md`.

## Кто с кем говорит
```
Loader --SOAP--> СПАРК(мок)         Loader --пишет--> Postgres (company_versions, company_groups, load_state)
Enrichment --REST--> /abs (мок)     Enrichment --пишет--> Postgres (bank_clients, company_snapshot) и Redis
Gateway --REST--> Client Info | Group Companies | Scoring
Client Info --читает--> Redis, затем Postgres (company_snapshot)
Group Companies, Scoring --читают--> Postgres (company_snapshot)
Scoring --gRPC--> ML Model
Postgres (outbox) --> Go Publisher --> Kafka company.changes --> Go Processor --> Kafka company.audit
```

## Postgres (`db/migrations/001_init.sql`)
| Таблица | Пишет | Читают |
|---|---|---|
| `company_versions` (SCD2), `company_groups`, `load_state` | Loader / Store | Enrichment |
| `bank_clients` | Enrichment | Enrichment |
| `company_snapshot` (актуальный срез, `data_as_of`) | Enrichment | Client Info, Group Companies, Scoring |

`load_state`: `initial_done` (`true` после первичной загрузки; по нему ждут Enrichment и demo.sh), `initial_loaded_at`, `last_sync_at` (время НАЧАЛА последнего успешного запроса GetChangedCompanies).

## Redis
- `company:{inn}` — готовый JSON в формате `CompanyInfo` (его строит `platform_common.mapping.to_company_info`), TTL = `CACHE_TTL_SECONDS`. Кладёт Enrichment, читает и дозаполняет при промахе Client Info.

## Внутренние REST (те же пути, что в контрактах Gateway)
- Client Info `:8004` — `GET /v1/companies/{inn}`
- Group Companies `:8005` — `GET /v1/companies/{inn}/group?onlyBankClients=`
- Scoring `:8002` — `GET /v1/companies/{inn}/scoring`
- Gateway `:8000` — все три наружу, Bearer `GATEWAY_TOKEN`, таймаут к нижним `UPSTREAM_TIMEOUT_SEC` (0.9 с)

## Ошибки и X-Request-Id
Формат `{code, message, traceId, details?}`; коды: `INVALID_REQUEST` (400), `UNAUTHORIZED` (401), `COMPANY_NOT_FOUND` (404), `INTERNAL_ERROR` (500), `SERVICE_UNAVAILABLE` (503), `UPSTREAM_TIMEOUT` (504).
`X-Request-Id` берём из запроса или генерируем и передаём вниз. Всё это даёт `platform_common.errors.install(app)`.
Gateway передаёт `X-Cache` из Client Info. В ответе группы `relation` может быть `null`, когда роль не пришла из СПАРК.

## gRPC (`proto/scoring.proto`)
- `GetInfo` — список признаков модели; `Predict` — признаки по именам (`numeric` / `categorical`).
- Scoring: `DEADLINE_EXCEEDED` → 504 `UPSTREAM_TIMEOUT`, `UNAVAILABLE` → 503 `SERVICE_UNAVAILABLE`, `INVALID_ARGUMENT` → 500.
- Ответ скоринга по контракту: `probability` (= score модели), `modelVersion`, `scoredAt`, `dataAsOf`.

## Признаки модели company-scoring-v1 (из `meta["feature_doc"]`)
| Имя | Тип | Определение |
|---|---|---|
| `companyAgeMonths` | numeric | полных месяцев с RegistrationDate до даты расчёта |
| `mainActivityCode` | categorical | код ОКВЭД строкой вида `62.01` |
| `status` | categorical | `ACTIVE` / `LIQUIDATING` / `LIQUIDATED` |
| `groupSize` | numeric | компаний в группе, **включая саму**; `0`, если группы нет |
| `groupBankClientsCount` | numeric | сколько **других** компаний группы — клиенты банка (себя не считаем) |

Расчёт: `services/scoring/app/features.py`. Дату расчёта сверить с `tools/expected.py` (сегодня или `dataAsOf`).
Версии для загрузки модели: scikit-learn 1.8.0, dill 0.4.0, pandas 2.3.3 (пины в `services/ml-model/requirements.txt`).
