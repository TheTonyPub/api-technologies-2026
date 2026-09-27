# Семинар 4 — стили взаимодействия API

В этой ветке находятся сервисы и материалы практической работы 4 по курсу «API-технологии»: REST, gRPC, WebSocket и event-driven обработка на примере детерминированного ML-инференса. Общая информация о курсе и домашних заданиях — в [README основной ветки](https://github.com/TheTonyPub/api-technologies-2026/blob/main/README.md).

## Материалы семинара

- [Задание в Markdown](seminar04.md) для публикации на dataprosvet.ru.
- [Главная страница](index.html) для seminar04.dataprosvet.ru.
- [Пример настройки Caddy](docs/Caddyfile.example) для серверного размещения.

Каждому студенту, который покажет преподавателю полностью выполненное задание с семинара 4, начисляется **+1 дополнительный балл**.

## Локальный запуск сервисов семинара 4

Для локального запуска нужны Git и Docker с Compose. В репозитории находится один Compose-проект для REST, gRPC, WebSocket, event-driven API, NATS и отдельного обработчика событий. Подробные задания и команды для серверного и локального взаимодействия с API приведены в [инструкции к семинару 4](seminar04.md).

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

1. Убедитесь, что демон Docker запущен, и проверьте обе команды:

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

   Оставьте `HOSTING_TYPE=local` и пустое `COMPOSE_PROFILES` для работы на своём компьютере; значение сети `seminar04-edge` в шаблоне используется только локально. Для серверного режима в `.env` задайте `HOSTING_TYPE=server`, `COMPOSE_PROFILES=server`, имя уже созданной Docker-сети Caddy в `CADDY_NETWORK` и `CADDY_NETWORK_EXTERNAL=true`. Профиль `server` добавляет контейнер `homepage` с nginx: он отдаёт корневой [index.html](index.html), смонтированный только для чтения. На общей сети у публичных сервисов есть постоянные псевдонимы `seminar04-rest-api`, `seminar04-grpc-api`, `seminar04-websocket-api`, `seminar04-event-api` и `seminar04-homepage`; [пример Caddyfile](docs/Caddyfile.example) использует их, чтобы не зависеть от совпадения коротких имён сервисов в других сетях Caddy. Режим `server` предназначен для оператора сервера; он не устанавливает Caddy и не публикует DNS. Не добавляйте секреты в Git.

4. Проверьте итоговую конфигурацию, соберите образы и поднимите контейнеры:

   ```bash
   docker compose config
   docker compose build
   docker compose up -d
   docker compose ps
   ```

   При смене `HOSTING_TYPE` повторно выполните `docker compose config`, затем пересоздайте сервисы командой `docker compose up -d --force-recreate`.

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

   Контрольная сборка на ARM64 (27 сентября 2026 года): REST — 63,6 МБ, gRPC — 66,3 МБ, WebSocket — 65,0 МБ, event API — 64,4 МБ, worker — 49,9 МБ, NATS — 25,7 МБ, дополнительный `homepage` на запрошенном `nginx:latest` — 181,6 МБ. Размер может отличаться на x86-64 и при обновлении базового образа; сравнивайте его с выводом своей сборки.

### Как изучить gRPC-контракт

В [transaction.proto](proto/transaction.proto) объявлены четыре типа вызовов: unary, server streaming, client streaming и bidirectional streaming. В репозитории также лежат сгенерированные [transaction_pb2.py](services/grpc/transaction_pb2.py) с protobuf-сообщениями и [transaction_pb2_grpc.py](services/grpc/transaction_pb2_grpc.py) с клиентским stub и серверной регистрацией. Сравните объявления `rpc` в схеме с методами и дескрипторами в этих двух файлах. Команды для вызова каждого метода через `grpcurl` приведены в [задании](seminar04.md#2-grpc-четыре-типа-вызовов).

Файлы сгенерированы `grpcio-tools==1.71.0` (protoc 5.29.0):

```bash
python -m grpc_tools.protoc -Iproto --python_out=services/grpc --grpc_python_out=services/grpc proto/transaction.proto
```

Генератор нужен только для изменения контракта: готовые модули уже включены в репозиторий и образ сервиса.

### Частые проблемы

- **Cannot connect to the Docker daemon / Docker Desktop is starting:** откройте Docker Desktop (macOS/Windows) или выполните `sudo systemctl start docker` (Ubuntu), затем повторите `docker version`.
- **Port is already allocated:** остановите приложение, занявшее порт, либо найдите контейнер командой `docker ps`. У сервисов используются порты `8011`–`8014` и `4222`.
- **WSL не видит Docker:** обновите WSL (`wsl --update`), включите WSL 2 backend и интеграцию дистрибутива в Docker Desktop, закройте и заново откройте WSL.
- **Образ не собирается при загрузке зависимостей:** проверьте соединение с зеркалом `dockerhub.timeweb.cloud` и PyPI, затем повторите `docker compose build`. Для Python-зависимостей используется установка бинарных wheels, поэтому ошибки доступности совместимого wheel нельзя обходить отключением этой проверки.
