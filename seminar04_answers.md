# Практическая работа 4. Стили взаимодействия с API

## 1. REST: Немедленный ответ

**Успешный запрос:**
* HTTP-код: `200`
* Результат: `{"risk_score":0.85,"risk_label":"high"}`

**Запрос с ошибкой (нет `monthly_spend`):**
* HTTP-код: `422`
* Результат: `{"detail":[{"type":"missing","loc":["body","monthly_spend"],"msg":"Field required","input":{"tenure_months":18,"support_tickets":2}}]}`

## 2. gRPC: Четыре типа вызовов

**Reflection (list/describe):**
* Сервис: `seminar04.v1.TransactionInference`
* Методы: `PredictBatch`, `PredictBatchStream`, `AggregateTransactions`, `PredictLive`.

**Успешный запрос (PredictBatch):**
* Вернул список предсказаний для `tx-1` и `tx-2` (risk_score, risk_label).

**Запрос с ошибкой (пропущен id):**
* Статус: `InvalidArgument`
* Сообщение: `transaction id must not be empty`

**Server streaming (PredictBatchStream):**
* Пришло два отдельных сообщения с id `tx-1` и `tx-2`. Каждое со своим id.

**Client streaming (AggregateTransactions):**
* Результат: `transaction_count: 2`, `average_risk: 0.53`, `high_risk_count: 1`

**Bidirectional streaming (PredictLive):**
* Для `tx-live-1`: `risk_score 0.213`, `risk_label low`.
* Для `tx-live-2`: `risk_score 0.848`, `risk_label high`.
* Ответ приходит сразу после отправки строки, не дожидаясь завершения ввода.

## 3. WebSocket: Поток предсказаний

* **Соединение:** `wss://seminar04.dataprosvet.ru/stream/v1/live`
* **Сообщение 1:** `{"temperature":65,"vibration":0.12,"rpm":1400}` -> Ответ: `{"anomaly_score":0.012,"anomaly":false}`
* **Сообщение 2:** `{"temperature":112,"vibration":0.91,"rpm":2800}` -> Ответ: `{"anomaly_score":0.616,"anomaly":true}`
* **Сообщение с ошибкой:** `{"temperature":65,"rpm":1400}` -> Ошибка: `invalid_telemetry, vibration Field required`.
* Соединение осталось открытым после ошибки.

## 4. Event-driven: Задание для worker

**Создание задачи:**
* HTTP-код: `202 Accepted`
* `job_id`: `71ec54c9-f964-4de6-9b8a-34ae174e8081`
* (При повторном запросе статуса сервер вернул 307 Redirect).

**Неверное тело (без records):**
* HTTP-код: `422`
* Ошибка: `{"detail":[{"type":"missing","loc":["body","records"],"msg":"Field required","input":{}}]}`

## Таблица сравнения стилей

| Сценарий | Стиль | Обоснование |
| :--- | :--- | :--- |
| **Бизнес-сервис: сразу показать данные клиента** | REST | Требуется немедленный ответ, синхронный запрос, нет фоновой обработки. |
| **ETL: принять пакет и сообщить о готовности после фоновой обработки** | Event-driven | Допустима фоновая обработка, ответ 202 Accepted, не требует постоянного соединения. |
| **ML: оценивать поток телеметрии без повторного соединения** | WebSocket | Требуется постоянное соединение для потока данных в обе стороны. |

## Объяснение про 202 и Event-driven

Ответ `202` означает только то, что задача принята. Для event-driven архитектуры нужен брокер сообщений (NATS JetStream), который сохранит задачу, и отдельный worker, который заберет её и выполнит в фоне.
