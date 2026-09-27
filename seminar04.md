# Практическая работа 4. Выбор стиля взаимодействия с API

В этой работе вы взаимодействуете с четырьмя сервисами, имитирующими ML-инференс: REST сразу возвращает предсказание, gRPC демонстрирует четыре типа вызовов для транзакций, WebSocket обрабатывает поток измерений в одном соединении, а event-driven API принимает задание для отдельного обработчика. Сравните, что отправляет клиент, когда получает ответ и как связываются запрос и результат.

Сервисы используют простые детерминированные демонстрационные правила, а не обученные модели. Работа выполняется на серверном стенде `seminar04.dataprosvet.ru`.

## Что понадобится

- `curl` для HTTP: [загрузка](https://curl.se/download.html); проверьте `curl --version`.
- `grpcurl` для gRPC: [установка](https://github.com/fullstorydev/grpcurl#installation); Homebrew: `brew install grpcurl`.
- `websocat` для WebSocket: [установка](https://github.com/vi/websocat#installation); Homebrew: `brew install websocat`.
- Команды ниже рассчитаны на macOS, Linux или WSL и оболочку Bash. Для Windows можно использовать WSL.

## Адреса и эндпоинты

Если на сервере включена Basic Auth, получите имя пользователя и пароль у преподавателя.

| Сервис | Серверный эндпоинт |
|---|---|
| REST prediction | `POST https://seminar04.dataprosvet.ru/rest/v1/predict` |
| REST docs | [GET https://seminar04.dataprosvet.ru/rest/docs](https://seminar04.dataprosvet.ru/rest/docs) |
| WebSocket live inference | `wss://seminar04.dataprosvet.ru/stream/v1/live` |
| Events: submit job | `POST https://seminar04.dataprosvet.ru/events/v1/jobs` |
| Events: job status/result | `GET https://seminar04.dataprosvet.ru/events/v1/jobs/{job_id}` |
| Events docs | [GET https://seminar04.dataprosvet.ru/events/docs](https://seminar04.dataprosvet.ru/events/docs) |
| gRPC reflection | `seminar04.dataprosvet.ru:443` (TLS) |
| gRPC unary | `seminar04.v1.TransactionInference/PredictBatch` |
| gRPC server streaming | `seminar04.v1.TransactionInference/PredictBatchStream` |
| gRPC client streaming | `seminar04.v1.TransactionInference/AggregateTransactions` |
| gRPC bidirectional streaming | `seminar04.v1.TransactionInference/PredictLive` |

В примерах серверных запросов заголовок авторизации передаётся переменной `$BASIC_HEADER`. Выполните подготовку **до начала записи терминала**, чтобы секрет не попал в журнал. Введите пароль скрыто; не включайте `set -x` и не запускайте `curl -v` или `grpcurl -v` при записи.

```bash
printf 'Basic Auth user: '; IFS= read -r BASIC_USER
printf 'Basic Auth password: '; IFS= read -rs BASIC_PASS; printf '\n'
BASIC_HEADER="Authorization: Basic $(printf '%s' "$BASIC_USER:$BASIC_PASS" | base64 | tr -d '\r\n')"
unset BASIC_PASS
```

При необходимости записи запустите `script -q seminar04.log` **только после** подготовки Basic Auth переменных, завершите `exit`. Не включайте в журнал пароли, токены, значение `$BASIC_HEADER` или содержимое `.env`. Не используйте `set -x`, `curl -v` или `grpcurl -v`; проверьте и удалите секреты из файла до отправки. Не публикуйте `.env`.

Не выводите `$BASIC_HEADER`, не записывайте его значение и не делитесь им. Если серверная Basic Auth отключена, удалите параметр `-H "$BASIC_HEADER"` из серверных команд.

## 1. REST: немедленный ответ

Сервис оценивает риск клиента по сроку обслуживания, расходам и числу обращений в поддержку. Успешный ответ содержит `risk_score` и `risk_label`.

**Сервер — успешный запрос:**

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/rest/v1/predict \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
```

Запишите HTTP-код и поля результата. Предсказание приходит в ответе на тот же вызов.

**Сервер — запрос с ошибкой** (пропущено обязательное `monthly_spend`):

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/rest/v1/predict \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"support_tickets":2}'
```

Запишите код и тело ошибки. Изучите [документацию REST](https://seminar04.dataprosvet.ru/rest/docs).

## 2. gRPC: четыре типа вызовов

gRPC передаёт структурированные protobuf-сообщения по HTTP/2. Изучите [исходную схему](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/proto/transaction.proto): ключевое слово `stream` у запроса или ответа определяет тип вызова. Reflection позволяет `grpcurl` обнаружить все методы без локального proto-файла. Ниже вы вызовете unary, server streaming, client streaming и bidirectional streaming; их различия объясняют [официальная документация gRPC](https://grpc.io/docs/what-is-grpc/core-concepts/) и [статья из задания](https://alirezafarokhi.medium.com/what-is-grpc-and-different-types-of-grpc-services-9b86a7267064). Во всех вариантах используется одна детерминированная оценка риска транзакции.

Сравните схему со сгенерированными модулями [transaction_pb2.py](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/services/grpc/transaction_pb2.py) (описания protobuf-сообщений) и [transaction_pb2_grpc.py](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/services/grpc/transaction_pb2_grpc.py) (клиентский stub и серверная регистрация методов). Эти файлы создаются из `.proto`, а не редактируются вручную.

**Unary: один пакет → один ответ. Сервер — reflection и успешный пакет:**

```bash
grpcurl -H "$BASIC_HEADER" seminar04.dataprosvet.ru:443 list
grpcurl -H "$BASIC_HEADER" seminar04.dataprosvet.ru:443 describe seminar04.v1.TransactionInference
grpcurl -H "$BASIC_HEADER" -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatch
```

Сопоставьте каждый элемент `predictions` с `id` транзакции.

**Сервер — запрос с ошибкой** (пропущено обязательное поле `id`):

```bash
grpcurl -H "$BASIC_HEADER" -d '{"transactions":[{"amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatch
```

Запишите gRPC status и сообщение ошибки. Если Basic Auth включена, серверный вызов передаёт её через HTTP/2 metadata заголовок `Authorization`.

**Server streaming: один пакет → последовательность предсказаний. Сервер:**

```bash
grpcurl -H "$BASIC_HEADER" -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatchStream
```

Сравните форму вывода с unary: здесь приходят отдельные сообщения `TransactionPrediction`, каждое со своим `id`.

**Client streaming: несколько транзакций → одна сводка. Сервер:**

```bash
printf '%s\n' \
  '{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2}' \
  '{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}' |
  grpcurl -H "$BASIC_HEADER" -d @ seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/AggregateTransactions
```

`grpcurl -d @` читает отдельные JSON-сообщения из stdin. Запишите поля ответа `transactionCount`, `averageRisk` и `highRiskCount`: сводка приходит после завершения клиентского потока. В `.proto` они названы `transaction_count`, `average_risk` и `high_risk_count`; protobuf JSON выводит имена в camelCase.

**Bidirectional streaming: отправка и ответы в одном вызове. Сервер:**

```bash
grpcurl -H "$BASIC_HEADER" -d @ seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictLive
```

Введите в открытом вызове по одной строке, нажимая Enter после каждой; затем завершите ввод Ctrl+D:

```json
{"id":"tx-live-1","amount":125.5,"international":false,"merchant_risk":0.2}
{"id":"tx-live-2","amount":980,"international":true,"merchant_risk":0.8}
```

Сопоставьте ответы с `id` входящих сообщений и отметьте, появляется ли ответ до завершения ввода. Сравните поведение с WebSocket: оба поддерживают обмен последовательностью сообщений, но контракт и жизненный цикл вызова различаются. Для всех потоковых методов применяются те же правила валидации транзакции, что и для unary.

## 3. WebSocket: несколько предсказаний на одном соединении

Клиент передаёт измерения температуры, вибрации и оборотов двигателя. Сервис возвращает `anomaly_score` и `anomaly` для каждого сообщения, пока соединение остаётся открытым.

**Сервер — откройте защищённое соединение** (опция `-H=` важна для передачи заголовка в `websocat`):

```bash
websocat -t -H="$BASIC_HEADER" wss://seminar04.dataprosvet.ru/stream/v1/live
```

В открытом сеансе отправьте по одной строке; после каждой нажмите Enter:

```json
{"temperature":65,"vibration":0.12,"rpm":1400}
{"temperature":112,"vibration":0.91,"rpm":2800}
```

Найдите ответ на каждое сообщение и сравните задержку с REST. Не закрывая соединение, отправьте некорректные данные — отсутствует `vibration`:

```json
{"temperature":65,"rpm":1400}
```

Сервис возвращает `error: "invalid_telemetry"` и оставляет соединение открытым. Отправьте ещё одно корректное сообщение. Завершите сеанс Ctrl+D.

## 4. Event-driven: задание для отдельного worker

HTTP API отвечает `202 Accepted` и `job_id`, затем публикует задание в NATS JetStream. Отдельный worker нормализует записи, выполняет inference и публикует результат. Ответ `202` означает, что работа принята; для получения результата клиент опрашивает статус по `job_id`.

**Сервер — отправьте пакет:**

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/events/v1/jobs \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1},{"customer_id":"c-2","monthly_usage":105,"support_tickets":4}]}'
```

Сохраните `job_id` из ответа в переменную `JOB_ID`, затем опрашивайте:

```bash
JOB_ID='вставьте-job_id-из-ответа'
curl -i -H "$BASIC_HEADER" "https://seminar04.dataprosvet.ru/events/v1/jobs/$JOB_ID"
```

Если состояние `pending`, повторите GET через короткий интервал до получения результата. Откройте [документацию Event API](https://seminar04.dataprosvet.ru/events/docs).

**Сервер — неверное тело** (нет списка `records`):

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/events/v1/jobs \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' -d '{}'
```

Запишите код и ошибку валидации.

## Сравнение стилей

Для каждого сценария укажите, нужен ли инициатору немедленный ответ, допустима ли фоновая обработка, нужен ли постоянный канал связи и почему выбранный стиль подходит.

| Сценарий | Стиль (REST / gRPC / WebSocket / event-driven) | Обоснование |
|---|---|---|
| Бизнес-сервис: получить данные клиента и сразу показать в интерфейсе |  |  |
| ETL: принять пакет, обработать независимо от клиента и сообщить о завершении |  |  |
| ML-инференс: оценивать поток телеметрии в одном соединении |  |  |

Объясните, почему endpoint, который возвращает `202`, сам по себе ещё не делает систему event-driven. Укажите роль брокера, отдельного worker и идентификатора корреляции.

## Что сдать

Каждому студенту, который покажет преподавателю полностью выполненное задание с семинара 4, начисляется **+1 дополнительный балл**.

1. Журнал команд и ответов по каждому стилю: один успешный и один ошибочный запрос, статус и адрес сервиса. Покажите, когда пришёл ответ и какие данные его связывают с запросом.
2. Для event-driven: `job_id`, время ответа `202`, результат опроса GET и совпадающий `job_id` в ответах.
3. Заполненную таблицу выбора стилей и краткое обоснование.
