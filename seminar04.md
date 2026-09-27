# Практическая работа 4. Выбор стиля взаимодействия с API

В этой работе вы взаимодействуете с четырьмя сервисами, имитирующими ML-инференс: REST сразу возвращает предсказание, gRPC принимает типизированный пакет транзакций, WebSocket обрабатывает поток измерений в одном соединении, а event-driven API принимает задание для отдельного обработчика. Сравните, что отправляет клиент, когда получает ответ и как связываются запрос и результат.

Сервисы используют простые детерминированные демонстрационные правила, а не обученные модели. **Основной вариант работы — серверный стенд** `seminar04.dataprosvet.ru`. В репозитории также сохранён полный локальный вариант с Docker Compose.

## Что понадобится

- `curl` для HTTP: [загрузка](https://curl.se/download.html); проверьте `curl --version`.
- `grpcurl` для gRPC: [установка](https://github.com/fullstorydev/grpcurl#installation); Homebrew: `brew install grpcurl`.
- `websocat` для WebSocket: [установка](https://github.com/vi/websocat#installation); Homebrew: `brew install websocat`.
- Для локального варианта: Docker Engine с Compose plugin или Docker Desktop, а также [NATS CLI](https://github.com/nats-io/natscli#installation).
- Команды ниже рассчитаны на macOS, Linux или WSL и оболочку Bash. Для Windows можно использовать WSL.

## Адреса и эндпоинты

Серверные URL ниже — основной вариант выполнения. Если на сервере включена Basic Auth, получите имя пользователя и пароль у преподавателя. Локальные адреса работают после запуска Compose и не требуют Basic Auth.

| Сервис | Серверный эндпоинт | Локальный эндпоинт |
|---|---|---|
| REST prediction | `POST https://seminar04.dataprosvet.ru/rest/v1/predict` | `POST http://127.0.0.1:8011/v1/predict` |
| REST docs | [GET https://seminar04.dataprosvet.ru/rest/docs](https://seminar04.dataprosvet.ru/rest/docs) | [GET http://127.0.0.1:8011/docs](http://127.0.0.1:8011/docs) |
| WebSocket live inference | `wss://seminar04.dataprosvet.ru/stream/v1/live` | `ws://127.0.0.1:8013/v1/live` |
| Events: submit job | `POST https://seminar04.dataprosvet.ru/events/v1/jobs` | `POST http://127.0.0.1:8014/v1/jobs` |
| Events: job status/result | `GET https://seminar04.dataprosvet.ru/events/v1/jobs/{job_id}` | `GET http://127.0.0.1:8014/v1/jobs/{job_id}` |
| Events docs | [GET https://seminar04.dataprosvet.ru/events/docs](https://seminar04.dataprosvet.ru/events/docs) | [GET http://127.0.0.1:8014/docs](http://127.0.0.1:8014/docs) |
| gRPC reflection | `seminar04.dataprosvet.ru:443` (TLS) | `127.0.0.1:8012` (plaintext) |
| gRPC inference | `seminar04.v1.TransactionInference/PredictBatch` | `seminar04.v1.TransactionInference/PredictBatch` |
| NATS JetStream | Не открыт наружу | `nats://127.0.0.1:4222` |

В примерах серверных запросов заголовок авторизации передаётся переменной `$BASIC_HEADER`. Выполните подготовку **до начала записи терминала**, чтобы секрет не попал в журнал. Введите пароль скрыто; не включайте `set -x` и не запускайте `curl -v` или `grpcurl -v` при записи.

```bash
printf 'Basic Auth user: '; IFS= read -r BASIC_USER
printf 'Basic Auth password: '; IFS= read -rs BASIC_PASS; printf '\n'
BASIC_HEADER="Authorization: Basic $(printf '%s' "$BASIC_USER:$BASIC_PASS" | base64 | tr -d '\r\n')"
unset BASIC_PASS
```

Не выводите `$BASIC_HEADER`, не записывайте его значение и не делитесь им. Если серверная Basic Auth отключена, удалите параметр `-H "$BASIC_HEADER"` из серверных команд. Локальные команды всегда выполняются без этого заголовка.

## Локальный запуск (альтернатива серверу)

Установите Docker по [инструкции для macOS](https://docs.docker.com/desktop/setup/install/mac-install/), [Windows](https://docs.docker.com/desktop/setup/install/windows-install/) или [Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Подробный порядок установки и устранения ошибок есть в [README репозитория](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/README.md#локальный-запуск-сервисов-семинара-4). Для локальной работы клонируйте репозиторий, переключитесь на ветку `seminar/04-api-interaction-styles`, скопируйте `.env.example` в `.env`, установите `HOSTING_TYPE=local` и запустите из корня репозитория:

```bash
docker compose build
docker compose up -d
docker compose ps
```

## 1. REST: немедленный ответ

Сервис оценивает риск клиента по сроку обслуживания, расходам и числу обращений в поддержку. Успешный ответ содержит `risk_score` и `risk_label`.

**Сервер — успешный запрос:**

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/rest/v1/predict \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
```

**Локально — успешный запрос:**

```bash
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
```

Запишите HTTP-код и поля результата. Предсказание приходит в ответе на тот же вызов.

**Сервер — запрос с ошибкой** (пропущено обязательное `monthly_spend`):

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/rest/v1/predict \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"support_tickets":2}'
```

**Локально — тот же запрос с ошибкой:**

```bash
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"support_tickets":2}'
```

Запишите код и тело ошибки. Изучите [серверную документацию REST](https://seminar04.dataprosvet.ru/rest/docs) или локально откройте [http://127.0.0.1:8011/docs](http://127.0.0.1:8011/docs).

## 2. gRPC: типизированный пакет транзакций

gRPC передаёт структурированное protobuf-сообщение по HTTP/2. Reflection позволяет `grpcurl` обнаружить сервис и вызвать его без локального proto-файла.

**Сервер — reflection и успешный пакет:**

```bash
grpcurl -H "$BASIC_HEADER" seminar04.dataprosvet.ru:443 list
grpcurl -H "$BASIC_HEADER" seminar04.dataprosvet.ru:443 describe seminar04.v1.TransactionInference
grpcurl -H "$BASIC_HEADER" -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatch
```

**Локально — reflection и успешный пакет:**

```bash
grpcurl -plaintext 127.0.0.1:8012 list
grpcurl -plaintext 127.0.0.1:8012 describe seminar04.v1.TransactionInference
grpcurl -plaintext -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
```

Сопоставьте каждый элемент `predictions` с `id` транзакции.

**Сервер — запрос с ошибкой** (пропущено обязательное поле `id`):

```bash
grpcurl -H "$BASIC_HEADER" -d '{"transactions":[{"amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatch
```

**Локально — тот же запрос с ошибкой:**

```bash
grpcurl -plaintext -d '{"transactions":[{"amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
```

Запишите gRPC status и сообщение ошибки. Если Basic Auth включена, серверный вызов передаёт её через HTTP/2 metadata заголовок `Authorization`.

## 3. WebSocket: несколько предсказаний на одном соединении

Клиент передаёт измерения температуры, вибрации и оборотов двигателя. Сервис возвращает `anomaly_score` и `anomaly` для каждого сообщения, пока соединение остаётся открытым.

**Сервер — откройте защищённое соединение** (опция `-H=` важна для передачи заголовка в `websocat`):

```bash
websocat -t -H="$BASIC_HEADER" wss://seminar04.dataprosvet.ru/stream/v1/live
```

**Локально — откройте соединение:**

```bash
websocat -t ws://127.0.0.1:8013/v1/live
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

Сервис возвращает `error: "invalid_telemetry"` и оставляет соединение открытым. Отправьте ещё одно корректное сообщение. Для ошибочного и последующего корректного сообщения повторите отдельно на серверном и локальном подключении. Завершите сеанс Ctrl+D.

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

**Локально — отправьте пакет и опросите результат:**

```bash
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1},{"customer_id":"c-2","monthly_usage":105,"support_tickets":4}]}'
JOB_ID='вставьте-job_id-из-ответа'
curl -i "http://127.0.0.1:8014/v1/jobs/$JOB_ID"
```

Если состояние `pending`, повторите GET через короткий интервал до получения результата. Откройте [серверную документацию Event API](https://seminar04.dataprosvet.ru/events/docs) или локально [http://127.0.0.1:8014/docs](http://127.0.0.1:8014/docs).

**Сервер — неверное тело** (нет списка `records`):

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/events/v1/jobs \
  -H "$BASIC_HEADER" -H 'Content-Type: application/json' -d '{}'
```

**Локально — то же неверное тело:**

```bash
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' -d '{}'
```

Запишите код и ошибку валидации. Прямое чтение событий доступно только локально, так как брокер NATS не открыт через Caddy:

```bash
nats --server nats://127.0.0.1:4222 stream ls
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.request.>'
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.result.>'
```

Найдите события `inference.request.<job_id>` и `inference.result.<job_id>`, затем сопоставьте идентификатор с HTTP-ответом и результатом GET. `nats stream view` открывает просмотр потока; завершите его клавишей, указанной CLI (обычно `q`). Для этой части нужен локальный Compose-стенд.

## Сравнение стилей

Для каждого сценария укажите, нужен ли инициатору немедленный ответ, допустима ли фоновая обработка, нужен ли постоянный канал связи и почему выбранный стиль подходит.

| Сценарий | Стиль (REST / gRPC / WebSocket / event-driven) | Обоснование |
|---|---|---|
| Бизнес-сервис: получить данные клиента и сразу показать в интерфейсе |  |  |
| ETL: принять пакет, обработать независимо от клиента и сообщить о завершении |  |  |
| ML-инференс: оценивать поток телеметрии в одном соединении |  |  |

Объясните, почему endpoint, который возвращает `202`, сам по себе ещё не делает систему event-driven. Укажите роль брокера, отдельного worker и идентификатора корреляции.

## Что сдать

1. Журнал команд и ответов по каждому стилю: один успешный и один ошибочный запрос, статус и подпись «сервер» или «локально». Покажите, когда пришёл ответ и какие данные его связывают с запросом.
2. Для event-driven: `job_id`, время ответа `202`, результат опроса GET и (для локального варианта) вывод NATS CLI с соответствующими request/result событиями.
3. Заполненную таблицу выбора стилей и краткое обоснование.

При необходимости записи запустите `script -q seminar04.log` **только после** подготовки Basic Auth переменных, завершите `exit`. Не включайте в журнал пароли, токены, значение `$BASIC_HEADER` или содержимое `.env`. Не используйте `set -x`, `curl -v` или `grpcurl -v`; проверьте и удалите секреты из файла до отправки. Не публикуйте `.env`.
