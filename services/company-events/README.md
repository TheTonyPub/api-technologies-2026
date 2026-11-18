# События компаний в Kafka

Kafka даёт потребителям возможность реагировать на изменения компаний независимо
от Loader и повторно читать события из топика. ИНН используется как ключ сообщения,
чтобы записи одной компании попадали в одну партицию.

## Что работает

```text
Kafka CLI → company.changes → Go processor → company.audit
```

Тестовое событие отправляет Kafka CLI. Go-обработчик за один запуск читает одну
запись и переносит её в `company.audit`. Выходная запись и оффсет группы
`company-audit-dev` фиксируются в одной транзакции Kafka. Чтение с
`read_committed` показывает только результат успешно завершённых транзакций.
Гарантия exactly-once здесь относится к обработке входной записи между двумя
топиками Kafka. Две входные записи с одним `event_id` будут обработаны отдельно.

## PostgreSQL outbox

При изменении уже загруженной компании SCD2 сохраняет новую версию и запись
в `company_outbox` в одной транзакции. Первая версия и повтор того же отчёта
событий не создают. `event_id` выдаёт PostgreSQL, а ограничение на `version_id`
гарантирует одну запись outbox на версию.

При первом запуске PostgreSQL Compose применит миграцию автоматически.
Если том уже существует, примени миграцию из корня репозитория перед запуском
обновлённого Loader.

```powershell
docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB -f /docker-entrypoint-initdb.d/002_company_outbox.sql'
```

`cmd/publisher` выбирает ожидающие строки по `version_id` и отправляет в
`company.changes` JSON с полями `event_id`, `version_id`, `inn`, `occurred_at`
и `type` со значением `CompanyChanged`. Ключ сообщения — ИНН. Продьюсер
блокирует выбранную строку на время отправки и ставит `published_at` после
подтверждения Kafka. При недоступности Kafka запись остаётся в очереди.
Если Kafka приняла сообщение, а PostgreSQL не сохранил отметку, продьюсер
может отправить сообщение повторно. Это доставка at-least-once со стабильным
`event_id`, по которому потребитель может распознать повтор.

### Запуск продьюсера

Запусти PostgreSQL, примени миграции и подними Kafka по инструкции ниже.
Задай `DATABASE_URL` с учётными данными и внешним портом локального PostgreSQL.
В PowerShell для настроек из `.env.example` команда выглядит так.

```powershell
$env:DATABASE_URL = 'postgresql://spark:spark@127.0.0.1:5432/spark'
go -C services/company-events run ./cmd/publisher
```

Продьюсер следит за очередью до Ctrl+C. Для проверки одной ожидающей записи
используй `go -C services/company-events run ./cmd/publisher -once`.
После изменения компании через Loader проверь новую строку в `company_outbox`.
После доставки у неё заполнится `published_at`, а сообщение появится
в `company.changes`. Команда `go -C services/company-events run ./cmd/processor`
переносит одну ожидающую запись входного топика в `company.audit`.

## Запуск

Нужны запущенный Docker Desktop и Go 1.24 или новее. Все команды ниже запускаются
из корня репозитория. Для демо достаточно Kafka, Go и синтетического события.

```powershell
docker compose -f compose.kafka.yml up -d kafka
docker compose -f compose.kafka.yml run --rm kafka-topics
go -C services/company-events test ./...
```

На хосте адрес брокера `localhost:29092`, внутри Docker — `kafka:9092`.
Для Go-команд можно переопределить адрес через `KAFKA_BROKERS`. На одном брокере
запускай один экземпляр обработчика с текущим `TransactionalID`.

## Ручная проверка отмены и коммита

На первом запуске топики пустые. Если демо уже запускали, сначала обработай
оставшиеся входные записи этой группы, чтобы следующей стала новая запись.
Команды ниже создают уникальный `event_id` для проверки результата.

```powershell
$eventId = 'demo-' + [guid]::NewGuid().ToString('N')
$event = @{ event_id = $eventId; inn = '7700000002'; type = 'CompanyChanged' } | ConvertTo-Json -Compress
"7700000002|$event" |
  docker compose -f compose.kafka.yml exec -T kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic company.changes --property parse.key=true --property 'key.separator=|'

function Read-DemoAudit {
  docker compose -f compose.kafka.yml exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic company.audit --from-beginning --isolation-level read_committed --timeout-ms 5000 |
    Select-String -SimpleMatch $eventId
}
```

**Отмена.** Обработчик отправит запись внутри открытой транзакции, затем отменит её.
В логе будет `aborted transaction for input offset=...`, а проверка покажет `0`.

```powershell
$env:KAFKA_DEMO_ABORT = '1'
try {
  go -C services/company-events run ./cmd/processor
} finally {
  Remove-Item Env:KAFKA_DEMO_ABORT
}
@(Read-DemoAudit).Count
```

**Коммит.** Запусти обработчик снова. В логе `committed input offset=...` должен
быть тот же оффсет, а проверка покажет `1`. Таймаут консольного consumer после
пяти секунд без новых записей завершает проверку.

```powershell
go -C services/company-events run ./cmd/processor
@(Read-DemoAudit).Count
```

При необходимости можно посмотреть сохранённую позицию группы. После коммита
`CURRENT-OFFSET` равен оффсету обработанной записи плюс один.

```powershell
docker compose -f compose.kafka.yml exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --group company-audit-dev --describe
```

Для остановки демо выполни `docker compose -f compose.kafka.yml down`.
