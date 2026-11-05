# Внешние сервисы для командных проектов (моки)

Учебные моки внешних систем, с которыми работают проекты команд в ДЗ 4. Все сервисы живут на одном домене
`https://api.external-services.dataprosvet.ru` за Caddy (TLS-сертификат Caddy получает сам), каждый под своим путём.

| Сервис | Путь | Протокол | Документация | Кейс |
|---|---|---|---|---|
| АБС банка | `/abs` | REST/JSON | `/abs/docs` | Антифрод, СПАРК |
| Бюро данных о клиентах «ДатаПрофиль» | `/client-data` | REST/JSON | `/client-data/docs` | Антифрод |
| СПАРК | `/spark` | SOAP 1.1 | `/spark/`, `/spark/ws?wsdl` | СПАРК |
| Мониторинг серверов ИС | `/monitoring` | REST/JSON | `/monitoring/docs` | Прогноз мощности |
| Уведомления (SendGrid + FCM) | `/notify` | REST/JSON | `/notify/docs` | Прогноз мощности |

## Общие правила

- **Данные генерируются, а не хранятся.** Клиенты, счета, операции, компании, изменения в СПАРК и метрики
  считаются формулой от фиксированного seed и времени, поэтому у всех команд одинаковые данные и рестарт их не меняет.
  Единственное, что хранится, — «входящие» `/notify` (SQLite, 7 дней).
- **Ключ команды** в заголовке `X-API-Key` (в `/notify` — `Authorization: Bearer <ключ>`, как у SendGrid/FCM).
  В `/spark` вместо ключа — логин и пароль для операции `Authenticate`.
- **Ошибки** — `{"code", "message", "traceId"}`, в ответе всегда `X-Request-Id`. `/notify` отвечает ошибками
  в формате SendGrid и Google API, `/spark` — SOAP Fault.
- **Лимиты** на ключ: 20 запросов/с (`/monitoring` — 50, `/spark` — 5 на команду). Превышение — 429 и `Retry-After`.
- **Сбои по запросу** — заголовок `X-Mock-Scenario`: `slow` (3 с), `timeout` (30 с, затем 504), `error` (500),
  `unavailable` (503), `ratelimit` (429). Фоновые сбои выключены (`MOCK_BG_ERROR_RATE=0`).
- `GET /<сервис>/health` — без ключа.

## Что нужно каждой команде

### Кейс «Прогноз требований к мощности серверов» (ddddda001)

| Внешняя система в архитектуре | Мок | Что использовать |
|---|---|---|
| Серверы ИС (агенты мониторинга) | `/monitoring` | `GET /v1/servers`, `GET /v1/information-systems`, `GET /v1/servers/{id}/metrics/current`, `GET /v1/servers/{id}/metrics` |
| Каналы уведомлений (Email / Push) | `/notify` | `POST /sendgrid/v3/mail/send`, `POST /fcm/v1/projects/{project}/messages:send`, `GET /inbox` |
| ML-модель прогноза | артефакт `capacity-forecast-v1.dill` | см. «Готовые модели» |

Особенности:
- **Агента мониторинга команда пишет сама.** Мок изображает серверы, а не агентов: агент раз в минуту читает
  `metrics/current` по каждому серверу и отправляет замер в свой Metrics Collector (`POST /v1/metrics`).
- `metrics/current` иногда отвечает 503 `NO_DATA` (около 0,5% минут без данных) — это нормальная ситуация для агента.
  Два сервера (`srv-013`, `srv-034`) offline: 503 `SERVER_OFFLINE`.
- История — до 366 дней назад, не больше 10 000 точек на запрос (`step=1m|5m|1h|1d`, `agg=mean|max`).
  Нужна для первичной заливки Data Store и прогнозов на 1 / 6 / 12 месяцев.
- У шести серверов в декабре 2026 нагрузка перейдёт 80%: диск у `srv-004`, `srv-018`, `srv-030`, пик CPU у
  `srv-009`, `srv-023`, `srv-037`. На них должен сработать Alert Worker.
- Уведомления никуда не уходят: всё отправленное видно в `GET /notify/inbox` и на странице
  `/notify/inbox/view?key=<ключ>`. Push на токен `invalid-...` вернёт 404 `UNREGISTERED`.

### Кейс «Антифрод» (azizanizomdzonova)

| Внешняя система в архитектуре | Мок | Что использовать |
|---|---|---|
| АБС: история клиента и операций (batch в ETL) | `/abs` | `GET /v1/clients`, `GET /v1/accounts/{id}`, `GET /v1/transactions`, `GET /v1/exports/transactions/{date}` |
| АБС: событие транзакции → наш Gateway | `/abs` | `GET /v1/transactions/live` — команда сама отправляет эти операции в свой `POST /v1/transactions/evaluate` |
| Внешние источники данных о клиенте | `/client-data` | `GET /v1/persons/{client_id}`, `POST /v1/persons:batch`, `GET /v1/regions`, `GET /v1/merchants/risk` |
| S3 / MinIO и Data Lake | не мокаются | поднимаются в docker compose команды (MinIO) |
| ML-модель | артефакт `antifraud-v1.dill` | см. «Готовые модели» |

Особенности:
- 2 000 физлиц, 3 000 счетов, история за 365 дней (около 750 тыс. операций, фрода около 2%), у каждой операции
  в истории есть `is_fraud`.
- Поток `live`: 60 новых операций в минуту без метки. Истинную метку отдаёт `GET /v1/transactions/{id}/label`
  через 5 минут — так команда проверяет качество своих вердиктов.
- Бюро данных медленное (200–600 мс) и с лимитом 20 запросов/с: звать его на каждую транзакцию в SLA 100 мс нельзя,
  риски регионов и мерчантов нужно заранее положить в Redis.
- Признаки модели считаются по истории счёта: `avg_amount_30d`, `tx_count_24h`, плюс `geo_risk` и `merchant_risk`
  из бюро, `amount` и `hour` из самой операции.

### Кейс «СПАРК: данные по юрлицам» (vegitobluefan)

| Внешняя система в архитектуре | Мок | Что использовать |
|---|---|---|
| СПАРК Интерфакс | `/spark` (SOAP) | `Authenticate`, `GetCompanyList`, `GetCompanyShortReport`, `GetCompanyGroup`, `GetChangedCompanies` |
| Внутренние данные банка для обогащения (`isBankClient`) | `/abs` | `GET /v1/legal-clients/{inn}`, `POST /v1/legal-clients:lookup`, `GET /v1/clients?type=legal` |
| ML Model скоринга | артефакт `company-scoring-v1.dill` | см. «Готовые модели» |
| CRM, АБС как потребители, Аналитический контур | не мокаются | роль потребителей играют тесты и curl команды |

Особенности:
- `/spark` — учебный SOAP-сервис по мотивам СПАРК, не настоящий API Интерфакса. WSDL: `/spark/ws?wsdl`,
  подходит для zeep, suds, JAX-WS и т. п. Сессия живёт 30 минут, `SessionId` передаётся в SOAP Header.
- 1 000 компаний с корректными ИНН/ОГРН, около 70 групп компаний. Около 3% компаний меняются каждый день
  (адрес, руководитель, КПП, ОКВЭД, статус вплоть до ликвидации, переход в другую группу) — материал для SCD2.
  `Revision` и `ActualDate` в карточке растут при каждом изменении, `GetChangedCompanies` отдаёт изменения с момента `Since`.
- Отчёты отвечают 0,5–2 с, лимит 5 запросов/с: требование «10 секунд на клиента» придётся учитывать в Loader.
- Клиентов банка среди компаний около 45%.

## Готовые модели (.dill)

Студенты модели не обучают: им выдаются готовые артефакты. Каждый файл — словарь из обычных объектов
scikit-learn и метаданных `meta` (признаки с описанием, порог, метрики, версии библиотек), своего кода внутри нет.

| Файл | Кейс | Что внутри | Как вызвать |
|---|---|---|---|
| `antifraud-v1.dill` | Антифрод | `model` (HistGradientBoostingClassifier), `meta.threshold` | `model.predict_proba(df)[:, 1]`, вердикт 1 если `>= threshold` |
| `company-scoring-v1.dill` | СПАРК | `model` (Pipeline: OneHot + LogisticRegression) | `model.predict_proba(df)[:, 1]` |
| `capacity-forecast-v1.dill` | Прогноз мощности | `models[горизонт][mean\|peak]` (Ridge), горизонты `1d`, `1m`, `6m`, `1y` | `models["1m"]["peak"].predict(df)[0]` |

```python
import dill, pandas as pd

art = dill.load(open("antifraud-v1.dill", "rb"))
meta = art["meta"]
row = {"amount": 45000, "avg_amount_30d": 1800, "tx_count_24h": 3,
       "geo_risk": 0.75, "merchant_risk": 0.8, "hour": 22}
score = art["model"].predict_proba(pd.DataFrame([row], columns=meta["features"]))[0, 1]
verdict = int(score >= meta["threshold"])
```

Для загрузки нужны `scikit-learn==1.8.0`, `dill`, `pandas` (см. `requirements-models.txt`), Python 3.11+.
Описание каждого признака — в `meta["feature_doc"]`. Модели обучены на данных этих же моков:
`python -m models.train_models` (результат в `models/artifacts/`, в git не хранится).

## Эталонные ответы для проверки

Данные моков детерминированы, поэтому что должна показать система команды, можно посчитать заранее
той же формулой и теми же моделями. Это эталон для сценария проверки на защите (и для будущего CI):

```sh
python -m tools.expected capacity --date 2026-11-19                 # какие серверы должны получить алерты
python -m tools.expected antifraud --from 2026-11-19T09:00:00Z      # precision/recall за час потока live
python -m tools.expected spark --at 2026-11-19T09:00:00Z --since 2026-11-12T00:00:00Z  # компании, клиенты, изменения
```

## Запуск

```sh
cp .env.example .env        # задать ключи команд и пароли СПАРК
docker compose up -d --build
```

Если на сервере уже работает свой Caddy, сервис `caddy` из compose не запускают
(`docker compose up -d --build abs client-data spark monitoring notify`), а блок из `caddy/Caddyfile.host`
добавляют в системный Caddyfile. Моки слушают `127.0.0.1:18101..18105`.

Тесты: `pip install -r requirements.txt pytest httpx && pytest -q tests`.

## Устройство

```
mocks/common/   ключи, сбои, лимиты, генераторы: bank.py (клиенты, счета, операции), companies.py (юрлица, группы, изменения)
mocks/<сервис>/app.py   FastAPI-приложение мока (spark — SOAP поверх FastAPI + lxml, WSDL в spark/wsdl.py)
mocks/monitoring/metrics.py   формула метрик серверов
models/train_models.py   обучение трёх моделей .dill
tools/expected.py   эталонные ответы для сценария проверки
caddy/   Caddyfile, вариант для системного Caddy, стартовая страница
```
