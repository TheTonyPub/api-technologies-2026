# Практическая работа 4. Выбор стиля взаимодействия с API
## 1. REST: немедленный ответ

### 1.1. Успешный запрос

Ответ:

```
HTTP/2 200
alt-svc: h3=":443"; ma=2592000
content-type: application/json
date: Mon, 28 Sep 2026 14:59:25 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 39

{"risk_score":0.85,"risk_label":"high"}
```

- **HTTP-код:** 200
- **risk_score:** 0.85
- **risk_label:** high


### 1.2. Запрос с ошибкой (нет `monthly_spend`)

Ответ:

```
HTTP/2 422
alt-svc: h3=":443"; ma=2592000
content-type: application/json
date: Mon, 28 Sep 2026 15:00:00 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 134

{"detail":[{"type":"missing","loc":["body","monthly_spend"],"msg":"Field required","input":{"tenure_months":18,"support_tickets":2}}]}

```

- **HTTP-код:** 422 
- Ошибка валидации: (`"type":"missing","loc":["body","monthly_spend"`)

---

## 2. gRPC: четыре типа вызовов

### 2.1. Сервер — reflection и успешный запрос

Первая команда:
```
grpc.reflection.v1alpha.ServerReflection
seminar04.v1.TransactionInference
```
Вторая команда:

```
seminar04.v1.TransactionInference is a service:
service TransactionInference {
  rpc AggregateTransactions ( stream .seminar04.v1.Transaction ) returns ( .seminar04.v1.TransactionScoreSummary );
  rpc PredictBatch ( .seminar04.v1.PredictBatchRequest ) returns ( .seminar04.v1.PredictBatchResponse );
  rpc PredictBatchStream ( .seminar04.v1.PredictBatchRequest ) returns ( stream .seminar04.v1.TransactionPrediction );
  rpc PredictLive ( stream .seminar04.v1.Transaction ) returns ( stream .seminar04.v1.TransactionPrediction );
}

```
Третья команда:

```
{
  "predictions": [
    {
      "id": "tx-1",
      "risk_score": 0.213,
      "risk_label": "low"
    },
    {
      "id": "tx-2",
      "risk_score": 0.848,
      "risk_label": "high"
    }
  ]
}

```
### Сопоставление результатов с идентификаторами транзакций

- **gRPC status:** OK
- Запрос — 1 сообщение с двумя транзакциями, ответ — 1 сообщение со списком `predictions`.

| id | risk_score | risk_label |
|---|---|---|
| tx-1 | 0.213 | low |
| tx-2 | 0.848 | high |

### 2.2. Сервер — запрос с ошибкой (пропущено id)

```
ERROR:
  Code: InvalidArgument
  Message: transaction id must not be empty
```
### Сравнение ошибок валидации REST и gRPC

| Что сравниваем | REST API | gRPC API |
| :--- | :--- | :--- |
| **Код ошибки** | `422 Unprocessable Entity` | `InvalidArgument` |
| **Формат** | JSON с деталями ошибки | Заголовок `Code` и текст `Message` |
| **Как сообщается о проблеме** | Показывает точный путь к полю: `["body", "monthly_spend"]` и причину `Field required` | Показывает сообщение от сервера: `transaction id must not be empty` |


### 2.3. Server streaming: один пакет, несколько ответов

```
{
  "id": "tx-1",
  "risk_score": 0.213,
  "risk_label": "low"
}
{
  "id": "tx-2",
  "risk_score": 0.848,
  "risk_label": "high"
}

```
**сравнение с unary:** запрос один, ответов несколько, каждое предсказание приходит отдельным сообщением `TransactionPrediction` со своим `id`. В unary те же результаты пришли одним сообщением списком


### 2.4. Client streaming: несколько транзакций, одна сводка

```
{
  "transaction_count": 2,
  "average_risk": 0.53,
  "high_risk_count": 1
}
```

- `transaction_count` = 2, `average_risk` = 0.53 (среднее из 0.213 и 0.848 ≈ 0.5305), `high_risk_count` = 1.
- **Ответ:** клиент отправляет несколько сообщений, сервер отвечает одной сводкойтолько после завершения клиентского потока. В задании сказано, что protobuf JSON выводит имена в camelCase (`transactionCount`), но в моём выводе `grpcurl` показал snake_case, как в `.proto`.

### 2.5. Bidirectional streaming: сообщения в обе стороны одного вызова

Ввод и ответы:

| Отправлено (id, amount, international, merchant_risk) | risk_score | risk_label |
|---|---|---|
| `tx-live-1`, 125.5, false, 0.2 | 0.213 | low |
| `tx-live-2`, 980, true, 0.8 | 0.848 | high |
| `tx-live-3`, 50.0, false, 0.3 | 0.255 | low |
| `tx-live-4`, 3467.0, true, 0.6 | 0.997 | high |
| `tx-live-5`, 12.0, true, 0.1 | 0.401 | low |
| `tx-live-6`, 756.0, true, 0.4 | 0.626 | high |

Пример вывода:

```
{"id":"tx-live-1","amount":125.5,"international":false,"merchant_risk":0.2}
{ "id": "tx-live-1", "risk_score": 0.213, "risk_label": "low" }
{"id":"tx-live-2","amount":980,"international":true,"merchant_risk":0.8}
{ "id": "tx-live-2", "risk_score": 0.848, "risk_label": "high" }
{"id":"tx-live-3","amount":50.0,"international":false,"merchant_risk":0.3}
{ "id": "tx-live-3", "risk_score": 0.255, "risk_label": "low" }
{"id":"tx-live-4","amount":3467.0,"international":true,"merchant_risk":0.6}
{ "id": "tx-live-4", "risk_score": 0.997, "risk_label": "high" }
{"id":"tx-live-5","amount":12.0,"international":true,"merchant_risk":0.1}
{ "id": "tx-live-5", "risk_score": 0.401, "risk_label": "low" }
{"id":"tx-live-6","amount":756.0,"international":true,"merchant_risk":0.4}
{ "id": "tx-live-6", "risk_score": 0.626, "risk_label": "high" }
```

**Ответ:** ответ на каждую транзакцию приходит до завершения ввода. Ответы сопоставляются с запросами по полю `id`. Оценки совпадают с unary для одинаковых транзакций, то есть все методы используют одну модель

**Сравнение с WebSocket:** оба держат постоянное соединение для обмена данными в реальном времени, но gRPC использует строгую схему (`protobuf`) и встроенные коды ошибок, а WebSocket передаёт обычный `JSON` и отправляет ошибки простыми сообщениями

---

## 3. WebSocket: поток предсказаний

### 3.1. Сервер — откройте защищённое соединение + ввод основных строк и дополнительных

* **Первое измерение:**
  * **Запрос:** `{"temperature":65,"vibration":0.12,"rpm":1400}`
  * **Ответ:** `{"anomaly_score":0.012,"anomaly":false}`

* **Второе измерение:**
  * **Запрос:** `{"temperature":112,"vibration":0.91,"rpm":2800}`
  * **Ответ:** `{"anomaly_score":0.616,"anomaly":true}`

* **Дополнительные измерения:**
  * **Запрос:** `{"temperature":24,"vibration":0.24,"rpm":2400}`
  * **Ответ:** `{"anomaly_score":0.024,"anomaly":false}`
  * **Запрос:** `{"temperature":199,"vibration":0.99,"rpm":1000}`
  * **Ответ:** `{"anomaly_score":1.0,"anomaly":true}`

**Сравнение времени ответа WebSocket и REST:** в REST на каждый запрос тратится время заново: открыть соединение, проверить защиту, отправить заголовки и получить ответ. Это занимает больше времени. В WebSocket соединение открывается один раз. Дальше сообщения летают туда обратно мгновенно, без лишней хрени

### 3.2. Сообщение с ошибкой

Ответ:

```
{"temperature":65,"rpm":1400}
{"error":"invalid_telemetry","detail":"1 validation error for Telemetry\nvibration\n  Field required [type=missing, input_value={'temperature': 65, 'rpm': 1400}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.10/v/missing"}

```

### 3.3. Корректное сообщение после ошибки

* **Запрос:** `{"temperature":123,"vibration":0.12,"rpm":1234}`
* **Ответ:** `{"anomaly_score":0.674,"anomaly":true}`

**Сравнение задержки ответа WebSocket и REST:** WebSocket открывает и защищает соединение только один раз в самом начале. В уже открытом WebSocket сообщения отправляются мгновенно без повторных проверок и лишних хрени. В REST каждый новый запрос вынужден заново открывать соединение и проходить авторизацию, из-за чего теряется время.

---

## 4. Event-driven: задание для отдельного worker

### 4.1. Сервер — успешное задание и получение статуса

Ввела сразу с примерами:

```
curl -i -X POST https://seminar04.dataprosvet.ru/events/v1/jobs \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1},{"customer_id":"c-2","monthly_usage":105,"support_tickets":4},{"customer_id":"c-3","monthly_usage":250,"support_tickets":0},{"customer_id":"c-4","monthly_usage":10,"support_tickets":5},{"customer_id":"c-5","monthly_usage":500,"support_tickets":2}]}'
```

```
HTTP/2 202
alt-svc: h3=":443"; ma=2592000
content-type: application/json
date: Tue, 29 Sep 2026 13:28:31 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 68

{"job_id":"e1751912-18d2-481b-b06c-d401a88e14b5","status":"pending"}
```

### 4.2. Повторный ввод и запись JOB_ID

Ввела: 

```
JOB_ID="e1751912-18d2-481b-b06c-d401a88e14b5"
curl -i -H "$BASIC_HEADER" "https://seminar04.dataprosvet.ru/events/v1/jobs/$JOB_ID"
```
Вывела:

```
HTTP/2 200
alt-svc: h3=":443"; ma=2592000
content-type: application/json
date: Tue, 29 Sep 2026 13:29:56 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 500

{"job_id":"e1751912-18d2-481b-b06c-d401a88e14b5","status":"completed","results":[{"customer_id":"c-1","normalized_usage":0.042,"risk_score":0.272,"risk_label":"low"},{"customer_id":"c-2","normalized_usage":0.105,"risk_score":0.575,"risk_label":"low"},{"customer_id":"c-3","normalized_usage":0.25,"risk_score":0.4,"risk_label":"low"},{"customer_id":"c-4","normalized_usage":0.01,"risk_score":0.56,"risk_label":"low"},{"customer_id":"c-5","normalized_usage":0.5,"risk_score":0.81,"risk_label":"high"}]}
```

Результаты:

| customer_id | normalized_usage | risk_score | risk_label |
|---|---|---|---|
| c-1 | 0.042 | 0.272 | low |
| c-2 | 0.105 | 0.575 | low |
| c-3 | 0.25 | 0.4 | low |
| c-4 | 0.01 | 0.56 | low |
| c-5 | 0.5 | 0.81 | high |


### Сервер — неверное тело

Вывела:

```
HTTP/2 422
alt-svc: h3=":443"; ma=2592000
content-type: application/json
date: Tue, 29 Sep 2026 12:26:26 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 90

{"detail":[{"type":"missing","loc":["body","records"],"msg":"Field required","input":{}}]}
```

- **Ошибка валидации(HTTP-код):** 422

---
## Сравнение стилей

| Сценарий | Стиль | Обоснование |
|---|---|---|
| Бизнес-сервис: сразу показать данные клиента | REST | Немедленный ответ нужен, тк пользователь ждёт данные на экране, фооновая обработка не нужна и постоянное соединение не нужно, тк достаточно одного запроса и ответа |
| ETL: принять пакет и сообщить о готовности после фоновой обработки | Event-driven (202 + брокер + worker) | Немедленный ответ не нужен, тк обработка большого пакета может идти в фоне. Клиент получает `job_id` и позже узнаёт статус. Постоянное соединение не нужно |
| ML: оценивать поток метрик без повторного соединения | WebSocket (или gRPC bidirectional streaming) | Немедленный ответ нужен по мере поступления каждого измерения, тк данные поступают постоянно(без прерываний). Нужно одно долгоживущее соединение, чтобы не платить за подключение на каждое сообщение XD |

### Почему HTTP endpoint с ответом 202 сам по себе не образует event-driven архитектуру

202 говорит, что задание принято, но ещё не обязательно завершено. Если сервер просто запускает задачу у себя внутри, то при его сбое или перезагрузке все задачи пропадают.
Event-Driven архитектура появляется только тогда, когда задача передаётся через брокер сообщений отдельному воркеру: API-сервис принимает запрос, мгновенно скидывает его в брокер сообщений и возвращает клиенту ответ `202` с номером задачи (`job_id`). Брокер сообщений работает как почтовыйв язик, сохраняет задачу на диск и дает гарантии??XD, что она не потеряется, даже если система сбойнет. вoркер как отдельная программа, которая забирает задачу из брокера и выполняет всю тяжёлую работу на фоне

---

## Текстовый журнал успешных и ошибочных команд и ответов для каждого сервиса

| Сервис | Адрес | Сценарий | Статус |
|---|---|---|---|
| REST | `/rest/v1/predict` | успех | HTTP 200 |
| REST | `/rest/v1/predict` | нет `monthly_spend` | HTTP 422 |
| gRPC | `PredictBatch` | успех | OK |
| gRPC | `PredictBatch` | пустой `id` | InvalidArgument |
| gRPC | `PredictBatchStream` | успех | OK (2 сообщения) |
| gRPC | `AggregateTransactions` | успех | OK (1 сводка) |
| gRPC | `PredictLive` | успех | OK (6 примеров) |
| WebSocket | `/stream/v1/live` | успех / нет `vibration` | ответ с оценкой / `invalid_telemetry`, соединение открыто |
| Event | `POST /events/v1/jobs` | успех | HTTP 202, `pending` |
| Event | `GET /events/v1/jobs/{job_id}` | после обработки | HTTP 200, `completed` |
| Event | `POST /events/v1/jobs` | пустое тело `{}` | HTTP 422 |


---

## Наблюдения о времени ответа и корреляции

**Время ответа**

- REST: каждый вызов, как отдельный round trip :P результат приходит сразу в ответе
- gRPC: используется HTTP/2 и одно соединени, в streaming ответы приходят по мере обработки, а в client streaming только после закрытия потока клиентом
- WebSocket: после 1 установленного соединения ответ на каждое сообщение приходит быстрее, чем в REST, так как нет повторного подключения и ввода новых запросов. Я не замеряла время, ну это даже видно, там я ввожу 435834 запросов, а тут 1 грубо говоря
- Event-driven: ответ 202 приходит быстро, но результат готов позже, в моём запуске между 202 (13:28:31) и получением `completed` (13:29:56) прошло 1 мин 25 сек, включая ввод по клаве

**Корреляция запроса и ответа**

| Стиль | Как сопоставляется ответ с запросом |
|---|---|
| REST | Ответ приходит в том же HTTP-вызове - че сопоставлять хз |
| gRPC unary / server streaming | По полю `id` транзакции в каждом `TransactionPrediction` |
| gRPC client streaming | Одна общая сводка на весь поток, отдельных `id` нет |
| gRPC bidirectional | По `id` транзакции, ответы приходят до завершения ввода |
| WebSocket | В ответе нет идентификатора, сопоставление по порядку сообщений |
| Event-driven | По `job_id`, полученному в ответе 202, результат запрашивается отдельным GET |


