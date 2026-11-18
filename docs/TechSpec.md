# ДЗ 4. Кейс СПАРК: техническое задание

Тестовые данные лежат в `db/dev/seed_snapshot.sql`.

Содержание:

1. [Общее для всех](#1-общее-для-всех)
2. [Данияр: Loader и инфраструктура](#2-данияр-loader-и-инфраструктура)
3. [Артём: хранилище (SCD2) и Enrichment](#3-артём-хранилище-scd2-и-enrichment)
4. [Савелий: API Gateway и Client Info](#4-савелий-api-gateway-и-client-info)
5. [Фёдор: Scoring и ML Model](#5-фёдор-scoring-и-ml-model)
6. [Павел: Group Companies, документы, README](#6-павел-group-companies-документы-readme)
7. [Стыки между участниками](#7-стыки-между-участниками)
8. [Что проверить перед сдачей](#8-что-проверить-перед-сдачей)
9. [Если останется время](#9-если-останется-время)

---

## 1. Общее для всех

### Что строим

Платформа забирает данные о юрлицах из СПАРК (в задании это SOAP-мок) и хранит их с историей изменений. Из АБС (тоже мок) она узнаёт, какие компании уже клиенты банка. На основе этого готовит актуальный срез и кэш и отдаёт данные наружу через один шлюз. Отдельно считает скоринг: вероятность того, что компания станет клиентом банка. Скоринг считает готовая модель `company-scoring-v1.dill`, обучать её не нужно.

### Как данные идут по системе

1. `Loader` авторизуется в СПАРК, получает список компаний, по каждой берёт краткий отчёт и данные о группе. Результат передаёт в модуль SCD2.
2. `SCD2` пишет версии компаний в таблицу `company_versions`. Новая версия появляется только если у компании реально изменились атрибуты. Старая версия при этом закрывается.
3. Когда первичная загрузка закончена, `Enrichment` спрашивает у АБС, какие компании клиенты банка, собирает таблицу `company_snapshot` (актуальный срез) и кладёт готовые карточки в Redis.
4. `Client Info` отдаёт карточку компании. Сначала смотрит в Redis, при промахе читает `company_snapshot` и кладёт результат в Redis.
5. `Group Companies` и `Scoring` читают `company_snapshot`.
6. `Scoring` собирает признаки для модели и вызывает `ML Model` по gRPC.
7. `Gateway` принимает запросы от CRM и АБС, проверяет Bearer-токен и передаёт запрос в нужный сервис.

### Что должно получиться в итоге

- Система поднимается одной командой `docker compose up --build` на чистой машине, без ручных шагов. Все контейнеры healthy, первичная загрузка завершается сама.
- Данные в моках одинаковы у всех команд и не меняются: 1000 компаний, 73 группы, 451 компания с `isBankClient = true`. В инкременте около 30 изменений в день, столько же новых версий SCD2.
- Внешние API вызываются правильно: нужные заголовки и ключ, верные пути, верный формат (SOAP для СПАРК, REST для АБС). Загружаются все страницы и все сущности.
- Повторный запуск загрузки не меняет число записей. После `docker compose restart` данные на месте.
- При сбоях моков (переменная `MOCK_SCENARIO`: `slow`, `timeout`, `error`, `unavailable`, `ratelimit`) сервисы не падают, повторяют запрос и отвечают ошибкой по контракту.
- REST-сервисы отвечают так, как описано в `contracts/*/openapi.yaml`. Если контракт приходится менять, меняем его и записываем изменение в `docs/CHANGES-hw4.md`.
- Скор через Gateway совпадает с прямым вызовом модели на тех же признаках.
- Сценарий проверки запускается одним скриптом `scripts/demo.sh` и сохраняет итоговые числа в `demo-result.json`.
- У каждого участника есть собственный код в своём компоненте и осмысленные коммиты. Каждый должен уметь объяснить свою часть.

### Где что лежит

| Папка | Что там |
|---|---|
| `services/loader`, `enrichment`, `gateway`, `client-info`, `group-companies`, `scoring`, `ml-model` | сами сервисы |
| `libs/common/platform_common` | общий код: формат ошибок, `X-Request-Id`, вызов нижних сервисов, преобразование строки среза в JSON по контракту |
| `db/migrations` | схема БД |
| `db/dev` | тестовые данные |
| `proto/scoring.proto` | описание gRPC между Scoring и ML Model |
| `contracts` | OpenAPI-контракты из ДЗ 2 |
| `docs` | договорённости, изменения, это ТЗ |
| `scripts` | `dev.py` (локальная разработка), `smoke.sh`, `demo.sh` (сценарий проверки) |

Порты:

| Сервис | Порт |
|---|---|
| gateway | 8000 |
| enrichment | 8001 |
| scoring | 8002 |
| loader | 8003 |
| client-info | 8004 |
| group-companies | 8005 |
| ml-model (gRPC) | 50051 |
| postgres | 5432 |
| redis | 6379 |

### Основные команды

Первый запуск (в `.env` нужны ключи, их выдал преподаватель; файл модели лежит в `models/` или скачивается по `MODEL_URL`):

```sh
cp .env.example .env
docker compose up --build
```

Каждодневные команды:

```sh
docker compose up --build -d              # поднять всё в фоне
docker compose ps                         # статус контейнеров
docker compose logs -f --tail=50 gateway  # логи одного сервиса
docker compose restart loader             # перезапуск одного сервиса
docker compose down -v                    # остановить и удалить данные БД
bash scripts/smoke.sh                     # быстрая проверка, что все сервисы отвечают
bash scripts/demo.sh                      # сценарий проверки
python scripts/dev.py test                # юнит-тесты без Docker
```

Если на Windows нет `make`, используем команды выше, они делают то же самое.

### Правила работы

- Каждый работает в своих папках. Общие файлы (`libs/common`, `docs/CONTRACTS.md`, `.env.example`, `docker-compose.yml`, `proto`) меняем только через PR с одобрением Данияра и сообщением в чат.
- Ветки называем `feat/имя-что`. Коммиты небольшие и по делу, например `feat(client-info): cache-aside через Redis`. Правки только документации и слияния веток разработкой не считаются.
- Ключи и пароли только в локальном `.env`. Перед каждым `git add` смотрим `git status`. Если ключ попал в историю коммитов, его придётся перевыпускать.
- Ключ команды, логин и пароль СПАРК и файл модели есть у Данияра. Он передаёт их каждому лично, не через git и не в общий чат.
- Схему БД меняем только новыми файлами `db/migrations/00N_*.sql`. Они применяются на пустом томе, поэтому после правки у всех нужен `docker compose down -v`.
- Любой исходящий вызов во внешний мок делаем с таймаутом. На 429 и 503 повторяем с паузой и учитываем заголовок `Retry-After`. Ответы 401 и 404 не должны ронять сервис. Заголовок `X-Mock-Scenario` добавляем только если `MOCK_SCENARIO` не пустая.
- Ошибки REST всегда в одном формате: `code`, `message`, `traceId`. Коды: `INVALID_REQUEST`, `UNAUTHORIZED`, `COMPANY_NOT_FOUND`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`, `UPSTREAM_TIMEOUT`. Для этого есть `platform_common.errors`, подключается одной строкой `install(app)`.

### Как разрабатывать, не дожидаясь друг друга

1. Поднять базы:

   ```sh
   docker compose up -d postgres redis
   ```

2. Залить тестовые данные в срез:

   ```sh
   docker compose exec -T postgres psql -U spark -d spark < db/dev/seed_snapshot.sql
   ```

   Это 8 вымышленных компаний с ИНН вида `999000000x`: группа с клиентами банка, группа без клиентов банка, компании без группы, одна ликвидируемая и одна ликвидированная.

   Перед реальной загрузкой их нужно убрать:

   ```sh
   docker compose exec postgres psql -U spark -d spark -c "DELETE FROM company_snapshot WHERE inn LIKE '999%';"
   ```

3. Запустить свой сервис на хосте:

   ```sh
   python scripts/dev.py local-env
   python scripts/dev.py имя-сервиса
   ```

   Для `scoring` и `ml-model` перед этим один раз: `python scripts/dev.py proto`.

4. Прогнать юнит-тесты:

   ```sh
   python scripts/dev.py test
   ```

---

## 2. Данияр: Loader и инфраструктура

Папки: `services/loader` (кроме `scd2.py`), `docker-compose.yml`, `scripts`, `Makefile`, `.env.example`.

### Как это работает

Loader единственный компонент, который общается со СПАРК. Он работает в фоновом потоке сервиса (функция `run_forever` в `main.py`): авторизуется, один раз делает первичную загрузку, потом по расписанию запрашивает изменения.

Любая ошибка (мок недоступен, БД недоступна) не убивает процесс. Цикл ждёт с нарастающей паузой и пробует снова. Сервис ещё отдаёт `GET /status` со счётчиками, по нему видно прогресс.

### Что уже есть

- Каркас сервиса и цикла, подключение к БД, чтение и запись `load_state`.
- Общий ограничитель частоты запросов (`rate_limiter.py`).
- Заглушки `soap_client.py`, `loader.py`, `incremental.py` с нужными сигнатурами.

### Что нужно реализовать

1. SOAP-клиент (`soap_client.py`) на библиотеке `zeep` по WSDL.

   Имена операций, полей и namespace берём из WSDL и со страницы мока `/spark/`. Посмотреть WSDL:

   ```sh
   python -m zeep https://api.external-services.dataprosvet.ru/spark/ws?wsdl
   ```

   Что делает клиент:
   - `Authenticate` вызывается при старте. Идентификатор сессии (`SessionId`) передаётся в SOAP-заголовке.
   - Сессия живёт около 30 минут. При ошибке `SESSION_EXPIRED` нужно авторизоваться заново и один раз повторить запрос.
   - На каждый вызов ставим таймаут (`zeep.transports.Transport(timeout=...)`).
   - Заголовок `X-Mock-Scenario` добавляем через `transport.session.headers`, только если переменная задана.
   - Ошибку `AUTH_FAILED` не глотаем: сервис должен громко сообщить, что логин или пароль неверные.
   - Ошибки `COMPANY_NOT_FOUND` и `INVALID_INN` означают, что одну запись нужно пропустить и записать в лог.
   - Пароль в лог не пишем.

2. Первичная загрузка (`loader.py`).

   Получаем список всех компаний (проходим все страницы). Для каждого ИНН берём краткий отчёт и данные о группе и вызываем `scd2.upsert_company` и `scd2.upsert_group`. Интерфейс этих функций описывает Артём в `services/loader/app/scd2.py`.

   Лимит СПАРК: 5 запросов в секунду на всю команду. Один отчёт отвечает за 0,5 до 2 секунд, поэтому последовательная загрузка идёт около 20 минут. Нужен пул из 8-10 потоков, все они ждут общий ограничитель частоты. Тогда вся загрузка занимает 3-4 минуты.

   Продолжение после падения: перед запросом пропускаем ИНН, у которых в БД уже есть текущая версия. Повторный запуск не создаст дублей и не будет качать всё заново.

   В конце загрузки записываем в `load_state` четыре ключа:
   - `initial_loaded_at`: время начала загрузки;
   - `last_sync_at`: то же значение;
   - `initial_done`: `true`;
- `initial_versions`: сколько версий лежит в `company_versions` сразу после первичной загрузки.

   Эти ключи ждут Enrichment и `demo.sh`. Время начала нужно ещё и эталонному скрипту проверки.

3. Инкремент (`incremental.py`).

   По расписанию (`INCREMENTAL_INTERVAL_SEC`, по умолчанию 300 секунд) вызываем `GetChangedCompanies` с параметром `since = last_sync_at`. Для каждого изменённого ИНН берём отчёт и группу и делаем upsert.

   В `last_sync_at` записываем время начала запроса, а не конца. Иначе изменения, которые пришли, пока шёл запрос, потеряются.

4. Сбои.

   `SOAP Fault`, `RATE_LIMIT`, ответы 429 и 503 обрабатываем повтором с экспоненциальной паузой. Лимит 5 запросов в секунду соблюдается всегда.

5. Служебные эндпоинты для сценария проверки. Скрипт `demo.sh` может ходить только в публичные API наших сервисов, поэтому Loader должен дать ему две вещи:
   - `POST /sync` запускает инкремент прямо сейчас (а не ждёт расписания) и возвращает, сколько версий SCD2 создано;
   - `GET /status` дополнительно отдаёт `initial_versions`, `initial_loaded_at` и `last_sync_at`. Число новых версий после инкремента это `versions` минус `initial_versions`, его сравнивают со значением `changes` из эталона.

### Инфраструктура

- `docker-compose.yml`: healthcheck, `depends_on` с `condition: service_healthy`, volumes для данных и лимиты памяти у Postgres и Redis уже сделаны. Следи, чтобы они не ломались при правках.
- В `.env.example` нужно вписать `MODEL_URL`, как только преподаватель скажет, откуда скачивать модель. Без этого чистый запуск у проверяющего не сработает.
- `scripts/demo.sh`: каркас готов, ты владелец. Шаги про карточку и группу наполняет Павел, шаг про скоринг Фёдор. Договаривайтесь через PR.
- В `demo-result.json` скрипт сохраняет итоговые числа: компаний, групп, клиентов банка, новых версий SCD2 после инкремента, время первичной загрузки, историю одной компании и три скора. Источники чисел: `GET :8003/status`, `GET :8001/status`, ответы Gateway.
- В конце нужен чистый прогон с нуля, числа в README и итоговый pull request.

### Как проверить

```sh
curl localhost:8003/status
curl -X POST localhost:8003/sync
```

После первичной загрузки в ответе `/status` `companies: 1000`, `groups: 73`, `initial_done: true`. После `POST /sync` число версий растёт только на реальные изменения.

Остальные проверки:
- Перезапуск контейнера `loader` не увеличивает число версий.
- Остановить контейнер посреди загрузки: после старта он должен дозагрузить остаток.
- С `MOCK_SCENARIO=ratelimit`, `unavailable` и `timeout` сервис не падает, в логах видны повторы.

### Нюансы

- Лимит СПАРК общий на всю команду. Два загрузчика одновременно или параллельные запуски у разных людей приведут к 429 у всех.
- Признак `isBankClient` в SCD2 не входит, это отдельное поле Enrichment.
- `.env` никому не пересылаем.

---

## 3. Артём: хранилище (SCD2) и Enrichment

Папки: `services/loader/app/scd2.py` (только этот файл), `db/migrations`, `services/enrichment`.

### Как это работает

Хранилище это Postgres. В таблице `company_versions` лежит вся история компании. Каждая запись это версия с интервалом действия (`valid_from`, `valid_to`) и флагом `is_current`. У компании в каждый момент ровно одна текущая версия, это гарантирует частичный уникальный индекс `ux_company_current`.

Enrichment берёт текущие версии, добавляет к ним название группы и признак клиента банка и записывает результат в `company_snapshot`. Готовые карточки он ещё кладёт в Redis. Все читающие сервисы работают только с `company_snapshot` и Redis, а не с историей.

### Что уже есть

- Схема в `db/migrations/001_init.sql`: `company_versions`, `company_groups`, `load_state`, `bank_clients`, `company_snapshot`.
- Заглушки в `scd2.py`.
- Каркас Enrichment: ожидание конца первичной загрузки (`wait.py` и фоновый поток в `main.py`) и `config.py` с функцией `abs_headers()`.

### Первое, что нужно сделать

Прочитать в ветке `infra/external-services` скрипт `tools/expected.py` (раздел `spark`). Нужно понять две вещи:
- откуда эталон берёт `valid_from` и `valid_to` в примере `scd2_demo` (время изменения в СПАРК или время нашей загрузки);
- какую дату считает "сегодня" при расчёте возраста компании.

Результат написать в чат. От него зависят и твой код, и скоринг Фёдора.

### Что нужно реализовать: хранилище

1. Функция `upsert_company(conn, company, now)` в `scd2.py`, всё в одной транзакции:
   - читаем текущую версию с блокировкой (`SELECT ... FOR UPDATE`);
   - считаем `attrs_hash`: sha256 от JSON бизнес-атрибутов с отсортированными ключами, без `id`, `valid_from`, `valid_to`, `is_current` и самого `attrs_hash`;
   - хэш совпал с текущим: ничего не делаем и возвращаем `False`;
   - хэш не совпал: сначала закрываем текущую версию (`valid_to = now`, `is_current = false`), потом вставляем новую (`valid_from = now`, `is_current = true`) и возвращаем `True`.

   Порядок важен, иначе уникальный индекс не даст вставить вторую текущую запись.

2. Функция `upsert_group(conn, group_id, group_name)`: обычный upsert в `company_groups`.

3. Схема. Если поля из ответа СПАРК не сходятся с колонками `company_versions`, добавь миграцию `002_*.sql`. Файл `001` не правим.

4. Просмотр истории. В `services/enrichment/app/history.py` сделать `GET /v1/internal/companies/{inn}/history`, который возвращает все версии компании с `valid_from`, `valid_to`, `is_current` и изменившимися полями. Роутер подключить в `main.py` одной строкой. Через этот эндпоинт `demo.sh` покажет, что у компании с изменившимся адресом или группой видна история.

5. Тесты в `services/loader/tests/test_scd2.py` (против Postgres из compose):
   - новая компания даёт одну версию;
   - те же данные повторно версий не добавляют;
   - изменённый адрес даёт вторую версию: у первой появляется `valid_to`, у второй `is_current`;
   - повторный прогон ничего не меняет.

### Что нужно реализовать: Enrichment

1. Признак `isBankClient`.

   Вызываем `POST /abs/v1/legal-clients:lookup` пачками до 500 ИНН (для 1000 компаний это два запроса). Формат запроса и ответа берём строго из документации: https://api.external-services.dataprosvet.ru/abs/docs

   Заголовок `X-API-Key` берём из `config.abs_headers()`, туда же добавляется `X-Mock-Scenario`, если он задан. Ставим таймаут. На 429 и 503 повторяем с учётом `Retry-After`. Ответы 401 и 404 сервис не роняют. Результат пишем в таблицу `bank_clients` (upsert).

2. Актуальный срез.

   Один запрос `INSERT ... SELECT ... ON CONFLICT (inn) DO UPDATE` собирает `company_snapshot` из текущих версий, `company_groups` и `bank_clients`. Поле `data_as_of` заполняем временем сборки среза. Это решение запиши в `docs/CONTRACTS.md`.

3. Redis.

   Для каждой компании кладём ключ `company:{inn}` со значением `platform_common.mapping.to_company_info(row)` в виде JSON и TTL из `CACHE_TTL_SECONDS` (через pipeline). Если Redis недоступен, пишем в лог и продолжаем работу.

4. Обновление после инкремента.

   Следи за значением `load_state.last_sync_at` и после каждого изменения пересобирай срез и кэш. Для 1000 строк можно пересобирать целиком.

5. `GET /status` в Enrichment. Нужен, чтобы `demo.sh` получил числа через публичный API, а не из БД. Отдаёт: число компаний в `company_snapshot`, число клиентов банка (`isBankClient = true`), число ключей в Redis, `data_as_of` последней сборки и признак, что сборка закончена.

### Как проверить

В Postgres:

```sh
docker compose exec postgres psql -U spark -d spark -c "SELECT count(*) FROM company_snapshot;"
docker compose exec postgres psql -U spark -d spark -c "SELECT count(*) FROM company_snapshot WHERE is_bank_client;"
```

Ожидаем 1000 и 451. Те же числа должен отдавать `GET localhost:8001/status`.

В Redis:

```sh
docker compose exec redis redis-cli DBSIZE
docker compose exec redis redis-cli TTL company:ИНН
```

Ключей около 1000, TTL положительный. После инкремента значения обновляются.

Остальные проверки:
- Повторный запуск Enrichment не создаёт дублей.
- С `MOCK_SCENARIO=unavailable`, `ratelimit`, `timeout` сервис не падает и повторяет запросы.

### Нюансы

- Лимит АБС 20 запросов в секунду, ключ общий на команду.
- `isBankClient` в хэш SCD2 не входит.
- Любая правка схемы это новый файл миграции и предупреждение всем в чат.

---

## 4. Савелий: API Gateway и Client Info

Папки: `services/gateway`, `services/client-info`.

### Как это работает

Gateway единственная точка входа для CRM и АБС. Он проверяет Bearer-токен и ИНН, передаёт запрос в нужный сервис с тем же `X-Request-Id` и возвращает ответ. Если нижний сервис упал или молчит, Gateway сам отвечает ошибкой в едином формате.

Client Info отдаёт карточку компании по ИНН и делает это быстро за счёт Redis.

### Что уже есть

Gateway работает как прокси:
- маршруты `/v1/companies/{inn}`, `/group` и `/scoring`;
- проверка токена (`GATEWAY_TOKEN`) и ИНН (ровно 10 цифр);
- сквозной `X-Request-Id`;
- таймаут к нижним сервисам 0,9 секунды (`UPSTREAM_TIMEOUT_SEC`);
- перевод ошибок нижних сервисов в наш формат.

В Client Info готовы маршрут, ответ 404 `COMPANY_NOT_FOUND` и вся обвязка. Функция `repository.get_company_info` пока заглушка.

### Что нужно реализовать: Client Info

В `services/client-info/app/repository.py` функция `get_company_info(inn)`:

1. Читаем из Redis ключ `company:{inn}`. Значение уже лежит в формате `CompanyInfo`, его просто возвращаем.
2. Если ключа нет, читаем строку из `company_snapshot` по `inn`, превращаем её через `platform_common.mapping.to_company_info`, кладём в Redis с TTL (`CACHE_TTL_SECONDS`) и возвращаем.
3. Если компании нет, возвращаем `None`. Маршрут сам вернёт 404 `COMPANY_NOT_FOUND`.
4. Если Redis недоступен, идём в БД и не падаем.
5. Чтобы было видно, что второй ответ приходит из кэша, возвращаем заголовок `X-Cache` со значением `MISS` или `HIT`. Чтобы Gateway его пробрасывал, нужно немного поправить `libs/common/platform_common/upstream.py`. Это отдельный PR, согласовать с Данияром.

### Что нужно реализовать: Gateway

1. Сверить каждый ответ и каждую ошибку с `contracts/api-gateway/openapi.yaml`: коды статусов, схемы, заголовки. Расхождения исправить в коде. Если сам контракт неудачный, обновить его и записать изменение в `docs/CHANGES-hw4.md`.
2. Проверить поведение при ошибках:
   - неверный ИНН или неверное значение `onlyBankClients` дают 400 `INVALID_REQUEST` с описанием проблемы в `details`;
   - нет токена или он неверный дают 401 `UNAUTHORIZED` (токен проверяется раньше валидации, так и должно быть).
3. Проверить 503 и 504 руками. Остановить `client-info`, `group-companies` или `scoring`: Gateway должен ответить 503 `SERVICE_UNAVAILABLE` быстрее чем за секунду. Если нижний сервис отвечает слишком долго, должен быть 504 `UPSTREAM_TIMEOUT`.
4. Сквозной `X-Request-Id`: один и тот же идентификатор должен попадать в логи Gateway и нижних сервисов. Для этого в общем middleware нужно добавить его в лог (правка `libs/common` через PR).
5. Тесты Gateway с подменой нижних сервисов (`httpx.MockTransport`).

### Как проверить

Запрос на тестовых данных (токен по умолчанию `change-me`):

```sh
curl -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000001
```

Ожидаем 200 и такой JSON:

```json
{"inn":"9990000001","ogrn":"1029990000001","kpp":"997001001","shortName":"ООО «Ромашка-Тест»",
 "status":"ACTIVE","registrationDate":"2012-03-15","legalAddress":"г. Москва, ул. Тестовая, д. 1",
 "mainActivity":{"code":"64.19","name":"Денежное посредничество прочее"},"groupId":"grp-dev-1",
 "isBankClient":true,"dataAsOf":"2026-11-08T06:00:00Z",
 "fullName":"Общество с ограниченной ответственностью «Ромашка-Тест»"}
```

Ошибки и скорость:

```sh
# без токена: 401 UNAUTHORIZED
curl -i localhost:8000/v1/companies/9990000001

# неверный ИНН: 400 INVALID_REQUEST
curl -i -H "Authorization: Bearer change-me" localhost:8000/v1/companies/123

# неизвестный ИНН: 404 COMPANY_NOT_FOUND
curl -i -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000099

# время ответа, должно быть меньше секунды
curl -w "%{time_total}\n" -o /dev/null -s -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000001
```

В каждой ошибке должен быть JSON с `code`, `message`, `traceId` и заголовок `X-Request-Id`.

### Нюансы

- Gateway не должен отвечать 500, если нижний сервис вернул ошибку. Функция `get_json` в `libs/common` уже переводит такие ответы в наш формат.
- В Redis кладём только корректный JSON карточки. Формат тот же, что пишет Enrichment.

---

## 5. Фёдор: Scoring и ML Model

Папки: `services/scoring`, `services/ml-model`, `proto`.

### Как это работает

ML Model отдельный gRPC-сервис. При старте он берёт файл `company-scoring-v1.dill` (из папки `models` или скачивает по `MODEL_URL`) и принимает признаки по именам.

Scoring по ИНН читает данные компании и её группы из `company_snapshot`, считает признаки, вызывает ML Model и отдаёт вероятность по контракту.

Признаки модели (из `meta["feature_doc"]`), имена строго такие:

- `companyAgeMonths`: полных месяцев с даты регистрации до даты расчёта.
- `mainActivityCode`: код ОКВЭД строкой, например `62.01`.
- `status`: `ACTIVE`, `LIQUIDATING` или `LIQUIDATED`.
- `groupSize`: сколько компаний в группе, включая саму компанию. Если группы нет, то 0.
- `groupBankClientsCount`: сколько ДРУГИХ компаний группы являются клиентами банка. Саму компанию не считаем.

### Что уже есть

- `proto/scoring.proto`: метод `Predict` принимает признаки по именам, метод `GetInfo` возвращает список признаков модели.
- ML Model целиком: `model_store.py` скачивает или находит файл, `server.py` отдаёт `Predict` и `GetInfo`.
- `services/scoring/app/features.py` с расчётом всех пяти признаков и тестами.
- `ml_client.py`: gRPC-клиент, переводит ошибки gRPC в наши коды.
- Маршрут `GET /v1/companies/{inn}/scoring`.

Не реализована только `repository.load_company_for_scoring`.

### Что нужно реализовать

1. `repository.load_company_for_scoring(inn)` в `services/scoring/app/repository.py`.

   Читаем строку компании из `company_snapshot`. Если у неё есть `group_id`, читаем все строки этой группы (включая саму компанию). Формат результата описан в докстринге функции. Если компании нет, возвращаем `None`.

2. Проверить сборку признаков в `features.py` на реальных данных.

   Дату расчёта возраста (сегодня или `data_as_of`) уточни у Артёма, он выяснит, как считает эталон. Зафиксируй решение в `scoring/app/main.py`.

3. Проверить связку Scoring и ML Model в Docker целиком.

   Версии библиотек в `services/ml-model/requirements.txt` (scikit-learn 1.8.0, dill 0.4.0, pandas 2.3.3) должны совпадать с теми, на которых обучена модель.

4. Сверить ответ `GET /v1/companies/{inn}/scoring` с `contracts/scoring-service/openapi.yaml`.

   Поля `probability`, `modelVersion`, `scoredAt`, `dataAsOf` и коды ошибок. Поправить расхождения.

5. Ошибки по контракту, а не 500:
   - неизвестный ИНН: 404 `COMPANY_NOT_FOUND`;
   - ML Model недоступна: 503 `SERVICE_UNAVAILABLE`;
   - ML Model не отвечает вовремя: 504 `UPSTREAM_TIMEOUT`.

   Значение `ML_TIMEOUT_SEC` в `scoring/app/config.py` поставь не больше 0,6 секунды. Gateway ждёт нижние сервисы 0,9 секунды, и если у Scoring таймаут больше, Gateway отрежет запрос раньше.

6. Скрипт `scripts/check_scoring.py`.

   Берёт три ИНН, получает скор через Gateway, независимо собирает признаки из БД, считает их напрямую вызовом `.dill` и сравнивает результаты с допуском 1e-6.

### Ориентиры на тестовых данных

Дата расчёта 08.11.2026:

| ИНН | Признаки | Скор |
|---|---|---|
| 9990000001 | возраст 175 мес., группа из 4 компаний, других клиентов банка 1, ОКВЭД 64.19, ACTIVE | около 0,3929 |
| 9990000011 | возраст 251 мес., группа из 2 компаний, клиентов банка 0, ОКВЭД 41.20, ACTIVE | около 0,4927 |
| 9990000021 | возраст 44 мес., без группы, ОКВЭД 56.10, ACTIVE | около 0,3097 |

При другой дате запуска возраст немного изменится и скор чуть сдвинется. Это нормально.

### Как проверить

```sh
# 200 и скор
curl -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000001/scoring

# ML Model остановлена: быстрый 503
docker compose stop ml-model
curl -i -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000001/scoring
docker compose start ml-model

# неизвестный ИНН: 404
curl -i -H "Authorization: Bearer change-me" localhost:8000/v1/companies/9990000099/scoring
```

### Нюансы

- Признаки передаются по именам. Колонки DataFrame берутся из `meta["features"]`, порядок значения не имеет.
- Неизвестный ОКВЭД модель переносит нормально (OneHot с `handle_unknown=ignore`).
- Не путать: в `groupSize` компания считает себя, в `groupBankClientsCount` нет.

---

## 6. Павел: Group Companies, документы, README

Папки: `services/group-companies`, `README.md`, `architecture`, `docs`.

### Как это работает

Group Companies по ИНН возвращает компании той же группы. Данные читает из `company_snapshot`. Параметр `onlyBankClients=true` оставляет в ответе только клиентов банка.

### Что уже есть

- Маршрут `GET /v1/companies/{inn}/group` и обработка 404.
- Фильтр `onlyBankClients` и сборка ответа в `platform_common.mapping.to_company_group`.
- Заглушка `repository.get_group`.

### Что нужно реализовать: сервис

1. `repository.get_group(inn)` в `services/group-companies/app/repository.py`.

   Читаем компанию из `company_snapshot` по ИНН.
   - Компании нет: возвращаем `None`, маршрут вернёт 404 `COMPANY_NOT_FOUND`.
   - Группа есть: возвращаем `group_id`, `group_name`, все строки группы (включая саму компанию) и `data_as_of`.
   - Группы нет: `group_id = None` и `rows` пустой список.

   Формат результата и SQL описаны в докстринге.

2. Сверить с `contracts/group-companies-service/openapi.yaml`.

   Нужно выяснить три вещи:
   - что означает `totalMembers` (всего в группе или после применения фильтра);
   - как выглядит ответ для компании без группы;
   - в каком порядке идут участники.

   Если сборку ответа нужно поправить, меняем `to_company_group` в `libs/common` (через PR) и обновляем тест в `libs/common/tests/test_mapping.py`.

3. Тесты сервиса на тестовых данных: группа с клиентами банка, группа без них, компания без группы, неизвестный ИНН.

### Как проверить

```sh
# 4 участника
curl -H "Authorization: Bearer change-me" "localhost:8000/v1/companies/9990000001/group"

# только 9990000001 и 9990000002
curl -H "Authorization: Bearer change-me" "localhost:8000/v1/companies/9990000001/group?onlyBankClients=true"

# группа есть, участников нет
curl -H "Authorization: Bearer change-me" "localhost:8000/v1/companies/9990000011/group?onlyBankClients=true"

# без группы: groupId null, members пустой
curl -H "Authorization: Bearer change-me" "localhost:8000/v1/companies/9990000021/group"
```

Без фильтра приходят все участники группы, с фильтром только клиенты банка.

### Что нужно реализовать: документы

1. Диаграмма.

   В `architecture/container.mmd` у Client Info и Group Companies заменить `Java/Python` на `Python`. Подпись связи Enrichment и АБС сократить до "Проверяет, клиент ли банка". Перегенерировать PNG:

   ```sh
   npx -p @mermaid-js/mermaid-cli mmdc -i architecture/container.mmd -o architecture/container.png -s 2
   ```

   Закоммитить через Git LFS, проверка: `git lfs ls-files`.

2. README, раздел про ДЗ 4:
   - команда запуска и порты;
   - таблица "участник и его компонент";
   - число загруженных записей (после первичной загрузки взять из `GET localhost:8003/status`: компании, группы, версии; число клиентов банка из Enrichment);
   - описание потока данных по шагам от получения из СПАРК до ответа CRM;
   - обоснование технологий: Postgres и SCD2 для истории, Redis как кэш, gRPC для ML-модели, REST для остального, Python;
   - ссылка на `docs/CHANGES-hw4.md`.

3. Таблица соответствия: каждое требование задания (обязательные условия и условия по кейсу) и какой файл или сервис его выполняет. Ведётся с самого начала и обновляется по мере готовности.

4. Изменения контрактов. Если кто-то меняет файлы в `contracts`, ты записываешь в `docs/CHANGES-hw4.md`, что изменилось и почему.

5. `scripts/demo.sh`: вместе с Данияром дописать шаги про карточку (два запроса подряд и неизвестный ИНН) и про группу (с фильтром и без).

---

## 7. Стыки между участниками

- Данияр отдаёт Артёму вызовы `upsert_company(conn, словарь, now)` и `upsert_group(...)`. Ключи словаря совпадают с колонками таблицы `company_versions`. Файл `services/loader/app/scd2.py`.
- Данияр отдаёт Артёму ключи таблицы `load_state`: `initial_done`, `initial_loaded_at`, `last_sync_at`.
- Артём отдаёт Савелию, Павлу и Фёдору таблицу `company_snapshot` и ключи Redis `company:{inn}` с готовым JSON карточки.
- Савелий отдаёт CRM и АБС маршруты Gateway по `contracts/api-gateway/openapi.yaml`.
- Савелий отдаёт Павлу и Фёдору единый формат ошибок и `X-Request-Id` (`libs/common/platform_common/errors.py`).
- Фёдор отдаёт Gateway маршрут `GET /v1/companies/{inn}/scoring`.
- Фёдор вызывает ML Model по gRPC (`proto/scoring.proto`).
- Павел отдаёт всей команде диаграммы, README, таблицу соответствия и сверку контрактов.

---

## 8. Что проверить перед сдачей

1. Чистый запуск на пустой машине:

   ```sh
   git clone ветка-проекта
   cp .env.example .env        # вписать ключи
   docker compose down -v
   docker compose up -d --build
   ```

   Все контейнеры `healthy`, первичная загрузка закончилась без ручных шагов.

2. Сценарий проверки:

   ```sh
   bash scripts/demo.sh
   ```

   Он проходит, создаёт `demo-result.json`, числа совпадают с `tools/expected.py`: 1000 компаний, 73 группы, 451 клиент банка, новые версии SCD2 равны значению `changes`.

3. Сбои. Те же шаги с `MOCK_SCENARIO=unavailable`, `ratelimit` и `timeout`: сервисы не падают и отвечают ошибкой по контракту.

   ```sh
   MOCK_SCENARIO=unavailable docker compose up -d loader enrichment
   ```

4. Повторный запуск загрузки не меняет число записей, после `docker compose restart` данные на месте.
5. У каждого участника свои коммиты в своём компоненте, в README есть таблица участников.
6. В README команда запуска, порты, число загруженных записей. Диаграмма (`mmd` и PNG через LFS) актуальна, `.proto` в репозитории, контракты актуальны.
7. В репозитории нет `.env`, ключей и `.dill`. Проверка:

   ```sh
   git ls-files | grep -E "\.env$|\.dill$"
   git log --all -S"текст-ключа" --oneline
   ```

   Обе команды должны ничего не вывести. В `.env.example` только имена переменных.
8. Pull request из ветки `homework/04-api-services` форка в ветку `homework/04-api-services` основного репозитория.

---

## 9. Если останется время

Необязательные доработки:
- метрики Prometheus и дашборд Grafana;
- автотесты и CI в GitHub Actions (`python scripts/dev.py test` уже запускает юнит-тесты);
- события об изменениях компаний в брокер сообщений.
