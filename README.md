# API-технологии — 2026

Репозиторий для сдачи командных работ по курсу. Домашние задания продолжают один семестровый проект: результат каждого следующего ДЗ опирается на результаты предыдущих.

- [Работы и инструкции](#работы-и-инструкции)
- [Сдача ДЗ](#как-сдавать-домашние-задания)
- [Дедлайны](#дедлайны)
- [Баллы и защита](#разбалловка-и-защита-дз)
- [Группы](#группы)

## Работы и инструкции

[Ссылка на варианты проектов](https://dataprosvet.ru/flutter.js.map#/courses/api-technologies/homeworks/team-case-architecture/read)
Разбивку по проектам смотрите в разделе [Группы](#группы)

| Работа | Что делаем | Инструкция |
|---|---|---|
| Семинар 1+2 | Выделяем сервисы и их взаимодействия, проектируем архитектуру, выбираем протоколы и переходим к контрактам API. | [Часть 1: архитектура](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/01-team-architecture) · [Часть 2: API-контракты](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/02-openapi-contract) |
| Семинар 4 | Сравниваем REST, gRPC, WebSocket и event-driven взаимодействие на примере ML-сервисов. | [Практическая работа 4](seminar04.md) · [Страница для seminar04.dataprosvet.ru](index.html) |
| ДЗ 1 | Описываем архитектуру назначенного кейса: C4-диаграммы, взаимодействие сервисов и обоснование выбранных технологий. | [Проработка архитектуры](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/01-team-architecture#домашнее-задание-1-архитектура-командного-проекта) |
| ДЗ 2 | Описываем все REST-взаимодействия между внутренними и внешними сервисами и готовим отдельный контракт OpenAPI 3.2.1 для каждого REST API. | [Разработка контрактов](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/02-openapi-contract#домашнее-задание-2-контракты-взаимодействия) |

## Как сдавать домашние задания

1. Один участник команды делает fork основного репозитория и добавляет остальных участников как collaborators в fork.
2. Команда переключается на ветку соответствующего семинара в основном репозитории:
   - ДЗ 1 — `seminar/01-team-architecture`;
   - ДЗ 2 — `seminar/02-openapi-contract`.
3. От ветки семинара команда создаёт в своём fork ветку `homework/<num>-<short-name>`, например `homework/01-team-architecture` или `homework/02-openapi-contract`.
4. Все материалы ДЗ и история их изменений находятся только в этой ветке домашнего задания. Ветка каждого следующего ДЗ должна сохранять все файлы предыдущих работ.
5. Команда открывает pull request из `homework/<num>-<short-name>` своего fork в соответствующую ветку `seminar/<num>-<short-name>` основного репозитория.
6. Для сдачи передаётся ссылка на pull request. В описании PR укажите состав команды, распределение ролей и итоговый commit.

Каждый участник команды должен сделать хотя бы один содержательный commit. Не объединяйте всю работу в один итоговый commit: история должна показывать последовательную работу над архитектурой, документацией и контрактами.

Бинарные изображения, документы, архивы, аудио и видео должны добавляться через Git LFS согласно правилам из `.gitattributes`.

## Локальный запуск сервисов семинара 4

Для работы нужны Git и Docker с Compose. В репозитории находится один Compose-проект для REST, gRPC, WebSocket, event-driven API, NATS и отдельного обработчика событий. Подробные задания и команды для взаимодействия с API приведены в [инструкции к семинару 4](seminar04.md).

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

   Оставьте `HOSTING_TYPE=local` и пустое `COMPOSE_PROFILES` для работы на своём компьютере; значение сети `seminar04-edge` в шаблоне используется только локально. Для серверного режима в `.env` задайте `HOSTING_TYPE=server`, `COMPOSE_PROFILES=server`, имя уже созданной Docker-сети Caddy в `CADDY_NETWORK` и `CADDY_NETWORK_EXTERNAL=true`. Профиль `server` добавляет контейнер `homepage` с nginx: он отдаёт корневой [index.html](index.html), смонтированный только для чтения. В [примере Caddyfile](docs/Caddyfile.example) корневой путь проксируется на `homepage:80`. Режим `server` предназначен для оператора сервера; он не устанавливает Caddy и не публикует DNS. Не добавляйте секреты в Git.

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
- **Образ не собирается при загрузке зависимостей:** проверьте соединение с Docker Hub/PyPI и повторите `docker compose build`. Для Python-зависимостей используется установка бинарных wheels, поэтому ошибки доступности совместимого wheel нельзя обходить отключением этой проверки.

## Дедлайны

Время указано по Москве (UTC+3).

| Домашнее задание | Soft deadline | Hard deadline |
|---|---|---|
| ДЗ 1 | `2026-09-21 23:59:59` | `2026-09-25 08:59:59` |
| ДЗ 2 | `2026-09-21 23:59:59` | `2026-09-25 08:59:59` |
| ДЗ 3 |  |  |
| ДЗ 4 |  |  |
| ДЗ 5 |  |  |
| ДЗ 6 |  |  |
| ДЗ 7 |  |  |
| ДЗ 8 |  |  |
| ДЗ 9 |  |  |
| ДЗ 10 |  |  |

- До soft deadline включительно можно получить полный балл за работу.
- После soft deadline и до hard deadline включительно максимальный балл за ДЗ составляет 50% от полного балла.

## Разбалловка и защита ДЗ

Всего за семестр можно получить 100 баллов. Допуск на зачет начинается с 30 баллов за семестр.
|Баллы|Оценка|
|---:|---:|
|85 - 100|5|
|70 - 84|4|
|60 - 69|3|
|0 - 59|не сдали|

>[!note]
>Оставшиеся баллы для зачета можно будет набрать на финальной защите проекта или за индивидуальные задания.

За каждое ДЗ можно будет получить от 0 до 5 баллов. Будет 2 дедлайна -- soft и hard.

|Когда сдали|Максимальный балл|
|---|---|
|до soft|5|
|после soft до hard|3|
|после hard|0|

>[!CAUTION]
>Дедлайн и возможность получить максимальный балл распространяются на всю команду.
>При этом, если команда сдала работу до soft, но у кого-то конкретного нет ни одного коммита, либо коммит с каким-то небольшим нефункциональным изменением, то его максимальный возможный балл снижается до 3.

>[!important]
>ДЗ делается в группах, но сдается индивидуально.
>Во время самостоятельной практики на семинаре необходимо подойти к преподавателю и защитить выполненное ДЗ, ответив на вопросы преподавателя.
>Вопросы будут касаться теории из лекций, практического применения технологий с семинаров, а также самого ДЗ.
>
>P.S. gpt-код будет видно сразу, поэтому советую использовать gpt осознанно, потому что необходимо будет объяснять, что и как работает, почему выбран тот или иной метод, почему написана именно такая функция и т.д.

## Группы
|Номер группы|Фамилии|Вариант задания| ссылка на форк репозитория|
|---|---|---|---|
|Группа 1| Низомджонова, Семенова, Плуталова, Власова, Якушев | 1| [Форк репозитория](https://github.com/azizanizomdzonova/api-technologies-2026) |
|Группа 2| Васильев, Керусов, Салтыков, Ракитин, Аринов | 2| |
|Группа 3| Асланова, Иванова, Самохин, Легалин | 3| |
