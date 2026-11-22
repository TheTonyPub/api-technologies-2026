# Антифрод: сервис синхронизации данных

Компонент 1 из кейса «Антифрод». Забирает данные из внешних систем и кладёт их туда, откуда их потом читают остальные сервисы:

| Что грузим | Откуда | Куда |
|---|---|---|
| Клиенты (физлица) | `GET /abs/v1/clients` | таблица `clients` в PostgreSQL |
| Счета | `GET /abs/v1/accounts/{id}` | таблица `accounts` |
| Операции за 30 дней | `GET /abs/v1/transactions` | таблица `transactions` |
| Профили клиентов | `POST /client-data/v1/persons:batch` | таблица `client_profiles` |
| Риски регионов | `GET /client-data/v1/regions` | Redis, hash `risk:region` |
| Риски мерчантов | `GET /client-data/v1/merchants/risk` | Redis, hash `risk:merchant` |

## Запуск

```sh
cp .env.example .env      # впишите свой ключ в API_KEY=
docker compose up --build postgres redis sync-service
```

Первая загрузка идёт сама, без ручных шагов. Она занимает несколько минут: у АБС нет списка счетов с деталями, поэтому 3 000 счетов берутся по одному запросу, а лимит 20 запросов в секунду.

Порты:

| Сервис | Порт на машине |
|---|---|
| sync-service (`/health`, `/stats`) | 8003 |
| PostgreSQL | 5432 |
| Redis | 6379 |

Проверка:

```sh
curl localhost:8003/health
curl localhost:8003/stats
```

В `/stats` видно, сколько чего загружено: `clients`, `accounts`, `transactions`, `profiles_found`, `profiles_not_found`, `redis_regions`, `redis_merchants`, а также `initial_tx_count` (сколько операций было после первой загрузки, его сверяют с эталоном) и `tx_loaded_until`.

Ожидаемые числа: 2 000 клиентов, 3 000 счетов, 600 мерчантов в Redis. Операций за 30 дней около 60 тысяч, точное число зависит от момента запуска.

## Как это работает

- При старте по очереди запускаются 4 загрузки: клиенты и счета, операции, профили, риски. Потом каждая повторяется по таймеру: операции раз в 5 минут, остальное раз в 1–6 часов (настраивается переменными `*_EVERY_MINUTES`).
- Если загрузка упала, сервис не падает: ошибка пишется в лог, повтор через минуту.
- Все списки читаются постранично, пока `nextCursor` не станет `null`.
- Повторный запуск не создаёт дублей: в PostgreSQL используется `ON CONFLICT`, в Redis `HSET` перезаписывает то же поле.
- Операции сохраняются страницами вместе с курсором. Если сервис упал посередине, он продолжает с того места, а не начинает заново. Счета, которые уже есть в базе, повторно не запрашиваются.
- При обновлении операций берётся окно с запасом в 1 час, а операции старше 30 дней удаляются.

### Внешние вызовы (`services/sync_service/http_client.py`)

- Таймаут 10 секунд на каждый запрос.
- Не больше 15 запросов в секунду (лимит моков 20).
- 429, 5xx и таймауты повторяются до 4 раз: ждём `Retry-After`, если он есть, иначе 1, 2, 4 секунды.
- 401 и 404 не повторяются. 404 на одном счёте пропускает только этот счёт. 404 от бюро по клиенту (`not_found` в ответе `persons:batch`) записывается в `client_profiles` с `found = false`.
- Если задана переменная `MOCK_SCENARIO`, она уходит заголовком `X-Mock-Scenario`.

## Что лежит в хранилищах (для остальных компонентов)

PostgreSQL, база `antifraud`:

- `clients(client_id, full_name, birth_date, gender, home_region_code, customer_since, segment, phone_masked)`
- `accounts(account_id, client_id, number, currency, opened_at, status)`
- `transactions(transaction_id, account_id, client_id, amount, currency, timestamp, merchant_id, mcc, channel, region_code, counterparty_account, is_fraud)`, индекс по `(account_id, timestamp)`
- `client_profiles(client_id, found, age, gender, ..., in_stop_list, sources, updated_at)`
- `sync_state(key, value)`: служебное (до какого времени загружены операции, курсор незаконченной загрузки)

Redis:

- `risk:region`: hash, поле `код региона`, значение `geo_risk` (например `HGET risk:region 77`)
- `risk:merchant`: hash, поле `merchant_id`, значение `merchant_risk` (например `HGET risk:merchant m-00001`). Для операций без мерчанта (переводы, банкомат) признак равен 0, это решает Gateway.

## Файлы

```
services/sync_service/
  main.py         запуск, таймер, /health и /stats
  loaders.py      четыре загрузки
  http_client.py  запросы наружу: таймаут, ретраи, лимит
  db.py           таблицы и сохранение в PostgreSQL
  config.py       настройки из переменных окружения
```

