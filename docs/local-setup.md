# Локальный запуск сервисов семинара 4

Для локального запуска нужны Git и Docker с Compose. В репозитории находится один Compose-проект для REST, gRPC, WebSocket, event-driven API, NATS и отдельного обработчика событий. Задание для серверного стенда находится в [seminar04.md](../seminar04.md).

### Установка Docker

Выберите инструкцию для своей системы. Устанавливайте Docker Desktop на macOS и Windows; на Ubuntu установите Docker Engine из официального apt-репозитория Docker.

**macOS**

1. Проверьте требования к версии macOS и архитектуре (Apple silicon или Intel) в [официальной инструкции](https://docs.docker.com/desktop/setup/install/mac-install/).
2. Загрузите подходящий Docker Desktop для Mac, откройте `Docker.dmg` и перенесите Docker в `Applications`.
3. Запустите Docker из папки `Applications` и завершите первоначальную настройку. Дождитесь, пока Docker Desktop сообщит, что движок запущен.

**Windows 10/11**

1. Установите или обновите WSL 2 из PowerShell от имени администратора: `wsl --install`, затем перезагрузите компьютер, если Windows этого попросит. Дополнительные сведения — [установка WSL](https://learn.microsoft.com/windows/wsl/install).
2. Скачайте Docker Desktop и запустите `Docker Desktop Installer.exe` из [официальной инструкции](https://docs.docker.com/desktop/setup/install/windows-install/). В установщике выберите backend WSL 2.
3. Откройте Docker Desktop, дождитесь запуска и в настройках включите интеграцию с используемым дистрибутивом Linux (Settings → Resources → WSL Integration).
4. Откройте терминал WSL (рекомендуется) либо PowerShell. Для команд ниже используйте WSL/Git Bash: они рассчитаны на POSIX shell. Если запускаете Compose из PowerShell, переключитесь в каталог проекта и создайте `.env` командами `Copy-Item .env.example .env`, затем откройте его для проверки через `notepad .env`.

**Ubuntu**

1. Добавьте официальный ключ и apt-репозиторий Docker:

   ```bash
   sudo apt update
   sudo apt install ca-certificates curl
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
   Types: deb
   URIs: https://download.docker.com/linux/ubuntu
   Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
   Components: stable
   Architectures: $(dpkg --print-architecture)
   Signed-By: /etc/apt/keyrings/docker.asc
   EOF
   sudo apt update
   ```

2. Установите движок, CLI, Buildx и Compose plugin:

   ```bash
   sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo systemctl enable --now docker
   ```

   Это официальная установка из [репозитория Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Для запуска команд без `sudo` следуйте [инструкции post-install](https://docs.docker.com/engine/install/linux-postinstall/); членство в группе `docker` предоставляет права уровня root.

### Проверка, сборка и запуск

1. Убедитесь, что демон Docker запущен, и выполните три проверки:

   ```bash
   docker version
   docker compose version
   docker run --rm hello-world
   ```

   Если Ubuntu сообщает об отказе в доступе к сокету, временно запускайте команды через `sudo` либо настройте права по инструкции выше. На Windows/macOS запустите Docker Desktop и проверьте, что открыт контекст Linux containers.

2. Получите ветку семинара 4:

   ```bash
   git clone --branch seminar/04-api-interaction-styles --single-branch https://github.com/TheTonyPub/api-technologies-2026.git
   cd api-technologies-2026
   ```

   Если GitHub запрашивает доступ, войдите в аккаунт, которому предоставлен доступ к репозиторию, и повторите команду (для HTTPS используйте настроенный Git Credential Manager или SSH URL). Если репозиторий уже клонирован, выполните `git fetch origin` и `git switch seminar/04-api-interaction-styles`.

3. Скопируйте шаблон окружения и выберите локальный режим:

   ```bash
   cp .env.example .env
   ```

   Оставьте `HOSTING_TYPE=local` и пустое `COMPOSE_PROFILES`. Не добавляйте секреты в Git.

4. Проверьте итоговую конфигурацию, соберите образы и поднимите контейнеры:

   ```bash
   docker compose config
   docker compose build
   docker compose up -d
   docker compose ps
   ```

5. Посмотрите логи:

   ```bash
   docker compose logs -f
   ```

   Остановить просмотр — `Ctrl+C`; контейнеры продолжат работу. Чтобы остановить и удалить контейнеры и сеть Compose, выполните `docker compose down`. Данные NATS удаляются только с отдельным `docker compose down -v`.

6. Посмотрите размеры собранных образов:

   ```bash
   docker compose images
   docker image ls
   ```

   Размер отображается в столбце `SIZE`. Для подробного изучения слоёв установленного образа можно использовать `docker image history ИМЯ_ОБРАЗА`.

   Контрольная сборка на ARM64 (27 сентября 2026 года): REST — 63,6 МБ, gRPC — 66,3 МБ, WebSocket — 65,0 МБ, event API — 64,4 МБ, worker — 49,9 МБ, NATS — 25,7 МБ. Размер может отличаться на x86-64 и при обновлении базового образа; сравнивайте его с выводом своей сборки.

### Как изучить gRPC-контракт

В [transaction.proto](../proto/transaction.proto) объявлены четыре типа вызовов: unary, server streaming, client streaming и bidirectional streaming. В репозитории также лежат сгенерированные [transaction_pb2.py](../services/grpc/transaction_pb2.py) с protobuf-сообщениями и [transaction_pb2_grpc.py](../services/grpc/transaction_pb2_grpc.py) с клиентским stub и серверной регистрацией. Сравните объявления `rpc` в схеме с методами и дескрипторами в этих двух файлах.

Файлы сгенерированы `grpcio-tools==1.71.0` (protoc 5.29.0):

```bash
python -m grpc_tools.protoc -Iproto --python_out=services/grpc --grpc_python_out=services/grpc proto/transaction.proto
```

Генератор нужен только для изменения контракта: готовые модули уже включены в репозиторий и образ сервиса.

### Локальные вызовы API

Установите [curl](https://curl.se/download.html), [grpcurl](https://github.com/fullstorydev/grpcurl#installation), [websocat](https://github.com/vi/websocat#installation) и [NATS CLI](https://github.com/nats-io/natscli#installation). На macOS `grpcurl` и `websocat` можно установить через Homebrew. Локальные вызовы не требуют Basic Auth.

| Сервис | Локальный адрес |
|---|---|
| REST | `http://127.0.0.1:8011/v1/predict`, [документация](http://127.0.0.1:8011/docs) |
| gRPC | `127.0.0.1:8012` (plaintext) |
| WebSocket | `ws://127.0.0.1:8013/v1/live` |
| Event API | `http://127.0.0.1:8014/v1/jobs`, [документация](http://127.0.0.1:8014/docs) |
| NATS JetStream | `nats://127.0.0.1:4222` |

**REST: успешный и ошибочный запросы**

```bash
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"monthly_spend":240.5,"support_tickets":2}'
curl -i -X POST http://127.0.0.1:8011/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"tenure_months":18,"support_tickets":2}'
```

**gRPC: reflection, unary и ошибка валидации**

```bash
grpcurl -plaintext 127.0.0.1:8012 list
grpcurl -plaintext 127.0.0.1:8012 describe seminar04.v1.TransactionInference
grpcurl -plaintext -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
grpcurl -plaintext -d '{"transactions":[{"amount":125.5,"international":false,"merchant_risk":0.2}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatch
```

**gRPC: server streaming** возвращает отдельное предсказание на каждую транзакцию:

```bash
grpcurl -plaintext -d '{"transactions":[{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2},{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}]}' \
  127.0.0.1:8012 seminar04.v1.TransactionInference/PredictBatchStream
```

**gRPC: client streaming** принимает последовательность JSON-сообщений из stdin и после её завершения возвращает сводку:

```bash
printf '%s\n' \
  '{"id":"tx-1","amount":125.5,"international":false,"merchant_risk":0.2}' \
  '{"id":"tx-2","amount":980,"international":true,"merchant_risk":0.8}' |
  grpcurl -plaintext -d @ 127.0.0.1:8012 seminar04.v1.TransactionInference/AggregateTransactions
```

**gRPC: bidirectional streaming** — откройте вызов, введите по одной строке JSON, после каждой нажмите Enter и завершите ввод Ctrl+D:

```bash
grpcurl -plaintext -d @ 127.0.0.1:8012 seminar04.v1.TransactionInference/PredictLive
```

```json
{"id":"tx-live-1","amount":125.5,"international":false,"merchant_risk":0.2}
{"id":"tx-live-2","amount":980,"international":true,"merchant_risk":0.8}
```

**WebSocket:** в одном открытом соединении отправьте две корректные строки, затем строку без `vibration`, затем ещё одну корректную строку. Сервис возвращает JSON после каждого сообщения; ошибочное сообщение не закрывает соединение.

```bash
websocat -t ws://127.0.0.1:8013/v1/live
```

```json
{"temperature":65,"vibration":0.12,"rpm":1400}
{"temperature":112,"vibration":0.91,"rpm":2800}
{"temperature":65,"rpm":1400}
{"temperature":65,"vibration":0.12,"rpm":1400}
```

**Event API:** отправьте пакет, скопируйте `job_id` из ответа и повторяйте GET до получения результата. Запрос без `records` показывает ошибку валидации.

```bash
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"customer_id":"c-1","monthly_usage":42,"support_tickets":1},{"customer_id":"c-2","monthly_usage":105,"support_tickets":4}]}'
JOB_ID='вставьте-job_id-из-ответа'
curl -i "http://127.0.0.1:8014/v1/jobs/$JOB_ID"
curl -i -X POST http://127.0.0.1:8014/v1/jobs \
  -H 'Content-Type: application/json' -d '{}'
```

Проверьте request и result события с одинаковым `job_id` напрямую в локальном NATS. Просмотр `nats stream view` интерактивный; завершите его клавишей, указанной CLI (обычно `q`). Брокер не опубликован через Caddy.

```bash
nats --server nats://127.0.0.1:4222 stream ls
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.request.>'
nats --server nats://127.0.0.1:4222 stream view INFERENCE --subject 'inference.result.>'
```

### Частые проблемы

- **Cannot connect to the Docker daemon / Docker Desktop is starting:** откройте Docker Desktop (macOS/Windows) или выполните `sudo systemctl start docker` (Ubuntu), затем повторите `docker version`.
- **Port is already allocated:** остановите приложение, занявшее порт, либо найдите контейнер командой `docker ps`. У сервисов используются порты `8011`–`8014` и `4222`.
- **WSL не видит Docker:** обновите WSL (`wsl --update`), включите WSL 2 backend и интеграцию дистрибутива в Docker Desktop, закройте и заново откройте WSL.
- **Образ не собирается при загрузке зависимостей:** проверьте соединение с зеркалом `dockerhub.timeweb.cloud` и PyPI, затем повторите `docker compose build`. Для Python-зависимостей используется установка бинарных wheels, поэтому ошибки доступности совместимого wheel нельзя обходить отключением этой проверки.
