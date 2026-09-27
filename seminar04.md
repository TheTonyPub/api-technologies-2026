# Практическая работа 4. Выбор стиля взаимодействия с API

В этой работе вы по очереди отправите запросы четырём сервисам, которые имитируют ML-инференс: REST сразу возвращает предсказание, gRPC принимает типизированный пакет транзакций, WebSocket обрабатывает поток измерений в одном соединении, а event-driven API принимает задание для отдельного обработчика. Сравните, что клиент отправляет, когда получает ответ и где проходит граница между сервисами.

Сервисы содержат простые детерминированные демонстрационные правила, а не обученные модели. Здесь важно исследовать протокол и форму взаимодействия.

## Что понадобится

- Docker Engine с Compose plugin или Docker Desktop. Шаги установки, настройки и запуска приведены в [README репозитория](README.md#локальный-запуск-сервисов-семинара-4).
- Терминал. Команды ниже написаны для macOS, Linux или WSL. В Windows используйте WSL либо адаптируйте команды к PowerShell.
- `curl` для REST и event API: [официальная страница загрузки](https://curl.se/download.html). Проверьте установку: `curl --version`.
- `grpcurl` для gRPC: [установка и готовые бинарные файлы](https://github.com/fullstorydev/grpcurl#installation), для Homebrew: `brew install grpcurl`.
- `websocat` для WebSocket: [готовые бинарные файлы и установка](https://github.com/vi/websocat#installation), для Homebrew: `brew install websocat`.
- NATS CLI для просмотра событий: [установка](https://github.com/nats-io/natscli#installation). Он подключается к локальному NATS на `127.0.0.1:4222`.

## Подготовка стенда

Из корня клона репозитория переключитесь на ветку `seminar/04-api-interaction-styles`, скопируйте `.env.example` в `.env`, оставьте `HOSTING_TYPE=local`, затем выполните:

```bash
docker compose build
docker compose up -d
docker compose ps
```

Проверьте, что API контейнеры запущены. В локальном режиме адреса сервисов:

| Стиль | Адрес | Операция |
|---|---|---|
| REST | `http://127.0.0.1:8011` | `POST /v1/predict` |
| gRPC | `127.0.0.1:8012` | `seminar04.v1.TransactionInference/PredictBatch` |
| WebSocket | `ws://127.0.0.1:8013` | `/v1/live` |
| Event-driven | `http://127.0.0.1:8014` | `POST /v1/jobs`, `GET /v1/jobs/{job_id}` |

На серверном стенде для HTTP и WebSocket используются `https://seminar04.dataprosvet.ru/rest`, `wss://seminar04.dataprosvet.ru/stream` и `https://seminar04.dataprosvet.ru/events`. gRPC доступен по `seminar04.dataprosvet.ru:443`, его метод сохраняет полный путь `/seminar04.v1.TransactionInference/PredictBatch`. Уточните у преподавателя, включена ли Basic Auth и как получить учётные данные. В NATS можно подключаться только к локальному стенду: брокер намеренно не проксируется наружу.

## 1. REST: запрос и немедленный ответ

REST подходит, когда клиенту нужен результат в рамках одного HTTP-вызова. Модель риска клиента получает срок обслуживания, месячные расходы и число обращений в поддержку.

Отправьте корректные данные:

```bash
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
```

Повторите запрос на хостинге:

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/rest/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
```

Запишите HTTP-код и поля `risk_score` и `risk_label`. Сравните время отправки и получения: предсказание приходит в ответе на тот же запрос.

Теперь пропустите обязательное поле `monthly_spend` и наблюдайте ошибку валидации:

```bash
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"support_tickets":2}'
```

Запишите код ответа и тело ошибки. Изучите контракт FastAPI: локально документация начинается с `http://127.0.0.1:8011/docs`; на сервере — `https://seminar04.dataprosvet.ru/rest/docs`.

## 2. gRPC: типизированный пакет транзакций

gRPC передаёт структурированное сообщение по HTTP/2. Сервер публикует reflection, поэтому `grpcurl` может показать методы и вызвать их без локального proto-файла.

Посмотрите доступные сервисы и описание метода:

```bash
grpcurl -plaintext 127.0.0.1:8012 list
grpcurl -plaintext 127.0.0.1:8012 describe seminar04.v1.TransactionInference
```

Отправьте пакет транзакций локальному сервису:

```bash
grpcurl -plaintext -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
```

На сервере подключение шифруется TLS на стандартном HTTPS-порту:

```bash
grpcurl -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  seminar04.dataprosvet.ru:443 seminar04.v1.TransactionInference/PredictBatch
```

Изучите ответ `predictions`: сопоставьте каждое предсказание с `id` транзакции. Для некорректного запроса опустите обязательный `id`:

```bash
grpcurl -plaintext -d '{"transactions":[{"amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
```

Запишите gRPC status и сообщение. Сравните gRPC-ошибку с HTTP-ошибкой REST.

## 3. WebSocket: несколько предсказаний на одном соединении

WebSocket сохраняет двунаправленное соединение открытым. В этой демонстрации клиент передаёт новые измерения температуры, вибрации и оборотов двигателя, а сервис рассчитывает оценку аномальности для каждого сообщения. Это поток последовательных выводов, а не один длинный вызов предсказания.

Откройте одно соединение командой:

```bash
websocat -t ws://127.0.0.1:8013/v1/live
```

Введите в открытом сеансе по одной строке и после каждой нажмите Enter:

```text
{"temperature":65,"vibration":0.12,"rpm":1400}
{"temperature":112,"vibration":0.91,"rpm":2800}
```

После каждой строки найдите ответ с `anomaly_score` и `anomaly`. Для хостинга команда подключения: `websocat -t wss://seminar04.dataprosvet.ru/stream/v1/live`.

Не закрывая локальный сеанс, введите сообщение с пропущенным полем:

```text
{"temperature":65,"rpm":1400}
```

Сервис возвращает JSON с `error: "invalid_telemetry"` и подробностью ошибки, после чего оставляет соединение открытым. Введите ещё одно корректное сообщение и убедитесь, что получаете новое предсказание. Завершите сеанс Ctrl+D. Запишите ответы и сопоставьте задержку внутри уже открытого соединения с HTTP round trip в REST.

## 4. Event-driven: принять задание и получить результат позже

Клиент отправляет пакет записей HTTP-запросом. Event API отвечает `202 Accepted` с идентификатором задания, публикует событие в NATS JetStream, а отдельный worker нормализует данные и выполняет ML-инференс. Результат публикуется отдельным событием. `202` означает, что работа принята, а не завершена.

Отправьте корректное задание:

```bash
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1},{"customer_id":"c-2","monthly_usage":105,"support_tickets":4}]}'
```

Ответ содержит `job_id` и начальный `status`. Сохраните идентификатор в переменную оболочки, затем запросите состояние:

```bash
JOB_ID='вставьте-job_id-из-ответа'
curl -i "http://127.0.0.1:8014/v1/jobs/$JOB_ID"
```

Если состояние ещё `pending`, повторите GET через короткий интервал; после обработки сохраните результаты и итоговый статус. На сервере вызовы идут через `/events`:

```bash
curl -i -X POST https://seminar04.dataprosvet.ru/events/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1}]}'
```

Отправьте неверное тело, в котором отсутствует список `records`:

```bash
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Зафиксируйте ошибку валидации. Затем исследуйте события брокера непосредственно на локальной машине:

```bash
nats --server nats://127.0.0.1:4222 stream ls
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.request.>'
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.result.>'
```

Найдите событие `inference.request.<job_id>` и соответствующее `inference.result.<job_id>`. Сопоставьте job ID из HTTP-ответа с идентификатором в subject/содержимом событий и результатом GET. Просмотр потока интерактивный; завершите его по инструкции NATS CLI. Эти команды рассчитаны на локальный Compose-стенд: на сервере порт NATS привязан только к `127.0.0.1` и не доступен через Caddy или извне.

## Сравнение стилей

Заполните таблицу примерами и аргументами. Для каждой строки укажите, нужен ли инициатору немедленный ответ, допустимо ли выполнение в фоне, и требуется ли постоянное соединение или пакетная обработка.

| Сценарий | Подходящий стиль (REST / gRPC / WebSocket / event-driven) | Почему он подходит или не подходит |
|---|---|---|
| Бизнес-сервис: запросить данные клиента и сразу показать их в интерфейсе |  |  |
| ETL: принять большой пакет, обработать независимо от клиента и сообщить о завершении |  |  |
| ML-инференс: оценивать последовательность телеметрии без нового соединения для каждого измерения |  |  |

Обоснуйте выбор на примере задания event-driven сервиса: почему простой HTTP endpoint с `202` ещё не означает, что работа стала event-driven? Укажите роль брокера и отдельного worker.

## Что сдать

1. Один текстовый журнал команд и вывода, сгруппированный по четырём сервисам. Для каждого приложите успешный и ошибочный запрос, код/статус и ответ. Подпишите локальный или серверный адрес.
2. Для event-driven сценария приложите `job_id`, время ответа `202`, результаты опроса GET и вывод NATS CLI с request/result событиями, содержащими соответствующую корреляцию.
3. Заполненную таблицу выбора стилей и краткие наблюдения о времени ответа и способе корреляции.

Записывайте локальный сеанс в macOS/Linux/WSL командой `script -q seminar04.log`, завершите `exit`. Не записывайте токены, пароли, заголовки авторизации и Basic Auth credentials в журнал. Если используете серверный стенд с Basic Auth, попросите безопасный способ передачи учётных данных и удалите их из подробного вывода и файла перед сдачей. Не публикуйте `.env`.
