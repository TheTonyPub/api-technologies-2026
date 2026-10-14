# API-технологии — 2026

## Семинар 6. Разработка REST API (и gRPC)

В этой работе вы пишете свой сервис и сдаёте его через pull request. Сервис должен запускаться: преподаватель клонирует PR, ставит зависимости из `requirements.txt`, запускает сервис и дёргает методы. Ту же проверку автоматически делает CI — PR принимается к защите только с зелёным CI.

- [Что сделать](#что-сделать)
- [Структура репозитория](#структура-репозитория)
- [Какие файлы можно менять](#какие-файлы-можно-менять)
- [REST: требования](#rest-требования)
- [gRPC: требования](#grpc-требования)
- [Как работает CI](#как-работает-ci)
- [Как сдавать](#как-сдавать)
- [Баллы и дедлайн](#баллы-и-дедлайн)

## Что сделать

1. **REST API** — все. Сервис на FastAPI с четырьмя HTTP-методами (`GET`, `POST`, `PUT`, `DELETE`), моделями данных для запросов и ответов и валидацией через `Field`. Ориентир — `user-service` из [семинара 3](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/03-api-interaction) ([код](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/03-api-interaction/services/user_service/main.py)). Можно сделать аналогичный по механике сервис со своей предметной областью: непростая копипаста 1 в 1 учитывается при сдаче.
2. **gRPC** — только те, кому разрешил преподаватель. Сервис с четырьмя типами взаимодействия (unary, server streaming, client streaming, bidirectional streaming), описанным `.proto` и сгенерированными файлами. Основа — gRPC из [семинара 4](https://github.com/TheTonyPub/api-technologies-2026/tree/seminar/04-api-interaction-styles) ([proto](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/proto/transaction.proto), [сервер](https://github.com/TheTonyPub/api-technologies-2026/blob/seminar/04-api-interaction-styles/services/grpc/server.py)).

## Структура репозитория

```text
rest-api/              ← REST-сервис (обязательно)
├── main.py            ← приложение FastAPI: app = FastAPI(...)
└── requirements.txt   ← обязательно fastapi и uvicorn
grpc/                  ← gRPC-сервис (только если вам разрешён gRPC)
├── proto/*.proto
├── *_pb2.py, *_pb2_grpc.py   ← сгенерированы из .proto
├── server.py          ← сервер на порту 50051
└── requirements.txt
templates/grpc/        ← шаблон gRPC-сервиса, его копируют в grpc/
ci/                    ← тесты CI
.github/workflows/     ← CI
```

В ветке уже лежат шаблоны: `rest-api/main.py` с заготовками всех четырёх методов и `rest-api/requirements.txt`. Шаблон gRPC лежит в `templates/grpc/`, а не в `grpc/`: CI проверяет gRPC только тогда, когда в корне есть папка `grpc/`.

## Какие файлы можно менять

PR может менять **только** файлы в двух папках:

| Папка | Что можно |
|---|---|
| `rest-api/` | любые файлы: `main.py`, `requirements.txt`, свои модули и т. д. |
| `grpc/` | любые файлы: `.proto`, сгенерированные `*_pb2.py`/`*_pb2_grpc.py`, `server.py`, `requirements.txt`, `ci_examples.json` и т. д. |

Всё остальное менять **нельзя**: `README.md`, `.gitignore`, `.gitattributes`, `ci/`, `.github/`, `templates/`. Удалять файлы вне этих двух папок тоже нельзя. Если PR затрагивает что-то кроме `rest-api/` и `grpc/`, первый же шаг CI («Структура PR») упадёт и покажет список лишних файлов. Состав команды и описание работы пишите в описании PR, а не в README.

## REST: требования

Сервис находится в `rest-api/`, приложение называется `app` и лежит в `rest-api/main.py`, то есть запускается командой `uvicorn main:app`.

### Методы

Минимальный набор — CRUD одного ресурса, как в `user-service`:

| Метод | Путь | Что делает | Успешный ответ |
|---|---|---|---|
| `POST` | `/v1/<resource>` | создаёт объект | `201` и идентификатор созданного объекта в теле |
| `GET` | `/v1/<resource>/{id}` | возвращает объект | `200` и объект |
| `PUT` | `/v1/<resource>/{id}` | изменяет объект | `2xx` и новое состояние объекта |
| `DELETE` | `/v1/<resource>/{id}` | удаляет объект | `204` (или `200`) |

Названия ресурса и параметра выбираете сами: `/v1/user/{user_id}`, `/api/books/{book_id}` и т. п. Путь объекта — это путь `POST` плюс один path-параметр. Идентификатор может быть числом или строкой (например, UUID). В ответе `POST` он должен лежать в поле с именем path-параметра (`user_id`) или в поле `id`.

Дополнительные методы (список объектов, поиск, health-check) добавлять можно — CI их тоже вызовет.

### Модели и валидация

- Тела `POST` и `PUT` — pydantic-модели (`BaseModel`).
- Поля моделей запросов описаны через `Field` с ограничениями: `ge`/`le`/`gt`/`lt`, `min_length`/`max_length`, `pattern`, `Enum` и т. п.
- У ответов `GET`, `POST`, `PUT` есть модель: `response_model=...` или аннотация возвращаемого типа.
- Укажите `examples=[...]` в `Field`. CI строит запросы по схеме OpenAPI и в первую очередь берёт значения из `examples`; для поля с `pattern` без `examples` подходящее значение может не найтись.

### Хранение данных

Базу данных не используйте (в том числе SQLite, как в семинаре 3). «База» — обычный питоновский словарь, объявленный в `main.py`, например:

```python
users: dict[int, UserResponse] = {}
```

Ключ — идентификатор объекта, значение — сам объект. Данные живут, пока запущен процесс, после перезапуска словарь пустой — так и задумано.

### Ошибки

- Несуществующий объект: `GET`, `PUT`, `DELETE` возвращают `404`.
- Тело, нарушающее ограничения модели, или тело без обязательного поля: `422` (FastAPI делает это сам, если ограничения описаны в `Field`).
- Ни один запрос не должен приводить к `5xx`.

### Запуск локально

Все команды в этом README вводятся в терминале (macOS/Linux — «Терминал», Windows — PowerShell или терминал в VS Code/PyCharm) по одной, из корня склонированного репозитория. Строки, начинающиеся с `#`, — пояснения, их вводить не нужно.

```sh
# перейти в папку REST-сервиса
cd rest-api

# создать виртуальное окружение Python в папке .venv
python -m venv .venv

# включить виртуальное окружение (macOS/Linux)
source .venv/bin/activate
# то же самое в Windows (PowerShell)
.venv\Scripts\Activate.ps1

# установить зависимости из requirements.txt
pip install -r requirements.txt

# запустить сервис на http://localhost:8000 с автоперезапуском при изменении кода
uvicorn main:app --reload
```

Остановить сервис — `Ctrl+C` в том же терминале. Пока сервис запущен, Swagger UI открывается в браузере по адресу http://localhost:8000/docs: там можно вызвать каждый метод кнопкой «Try it out».


## gRPC: требования

1. Скопируйте шаблон в папку `grpc/` (в терминале, из корня репозитория):

   ```sh
   # скопировать папку templates/grpc в новую папку grpc (macOS/Linux)
   cp -r templates/grpc grpc
   # то же самое в Windows (PowerShell)
   Copy-Item -Recurse templates/grpc grpc
   ```

2. Опишите свой сервис в `grpc/proto/*.proto` (шаблон — `item.proto`). В сервисе должны быть все четыре типа вызовов:
   - `rpc A (Req) returns (Resp)` — unary;
   - `rpc B (Req) returns (stream Resp)` — server streaming;
   - `rpc C (stream Req) returns (Resp)` — client streaming;
   - `rpc D (stream Req) returns (stream Resp)` — bidirectional streaming.
3. Сгенерируйте код и закоммитьте сгенерированные файлы:

   ```sh
   # перейти в папку gRPC-сервиса
   cd grpc

   # создать и включить виртуальное окружение (в Windows: .venv\Scripts\Activate.ps1)
   python -m venv .venv
   source .venv/bin/activate

   # установить зависимости сервиса и генератор кода grpcio-tools
   pip install -r requirements.txt -r requirements-dev.txt

   # сгенерировать item_pb2.py и item_pb2_grpc.py из proto/item.proto в текущую папку
   python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/item.proto
   ```

   Для файла `X.proto` в `grpc/` должны лежать `X_pb2.py` и `X_pb2_grpc.py`. Сгенерированные файлы руками не редактируют: поменяли `.proto` — сгенерируйте заново.
4. Реализуйте методы в `grpc/server.py`. Сервер запускается командой `python server.py` и слушает порт `50051`.
5. Проверьте сервис, например, через [`grpcurl`](https://github.com/fullstorydev/grpcurl) (в шаблоне включён reflection):

   ```sh
   # терминал 1, в папке grpc: запустить сервер на порту 50051 (остановить — Ctrl+C)
   python server.py

   # терминал 2: показать список сервисов, которые отдаёт сервер
   grpcurl -plaintext localhost:50051 list

   # терминал 2: вызвать unary-метод GetItem с запросом {"id": "1"}
   grpcurl -plaintext -d '{"id": "1"}' localhost:50051 homework.v1.ItemService/GetItem
   ```

CI вызывает каждый метод с автоматически заполненными сообщениями: строки вида `<имя_поля>-1`, числа `1`, `true`, первый ненулевой элемент enum, по два элемента в `repeated`. Каждый вызов должен завершиться статусом `OK`, а потоковые методы должны вернуть хотя бы одно сообщение. Если вашим методам нужны конкретные значения, положите их в `grpc/ci_examples.json` (JSON-формат protobuf, ключ — имя метода):

```json
{
  "GetItem": [{"id": "item-1"}],
  "CreateItems": [{"id": "a", "price": 10}, {"id": "b", "price": 20}]
}
```

## Как работает CI

Workflow `.github/workflows/homework-06.yml` запускается на каждый PR в эту ветку.

1. **Структура PR.** Есть `rest-api/main.py` и `rest-api/requirements.txt`; PR меняет только файлы в `rest-api/` и `grpc/`.
2. **REST.** На чистом Python 3.13 ставятся зависимости из `rest-api/requirements.txt`, сервис запускается командой `uvicorn main:app --host 0.0.0.0 --port 8000`. Затем тесты `ci/rest_tests` читают `/openapi.json` и проверяют:
   - в `requirements.txt` есть `fastapi` и `uvicorn`;
   - в схеме есть методы `GET`, `POST`, `PUT`, `DELETE`;
   - у `POST`/`PUT` тело — модель с ограничениями `Field`, у `GET`/`POST`/`PUT` описан ответ;
   - сценарий CRUD: `POST` → `GET` (поля совпадают) → `PUT` → `GET` (изменения сохранились) → `DELETE` → `GET` = `404`; ответы соответствуют схемам из OpenAPI;
   - `GET`/`PUT`/`DELETE` несуществующего объекта возвращают `404`;
   - тела с нарушением каждого ограничения и без обязательных полей возвращают `422`;
   - каждая операция из схемы вызывается хотя бы раз и не отвечает `5xx`.
3. **gRPC** — только если в PR есть папка `grpc/`, иначе job пропускается. Ставятся зависимости из `grpc/requirements.txt`, запускается `python server.py`. Тесты `ci/grpc_tests` компилируют ваши `.proto`, проверяют наличие сгенерированных `*_pb2.py`/`*_pb2_grpc.py`, наличие всех четырёх типов вызовов и вызывают каждый метод.

Если CI красный, откройте упавший job: в тексте ошибки указаны метод, отправленный запрос и полученный ответ, а в конце — логи сервиса.

## Как сдавать

1. Сделайте fork репозитория (или используйте fork команды) и создайте в нём ветку от `seminar/06-rest-api-development`, например `homework/06-rest-api`.
2. Реализуйте REST в `rest-api/` и, если разрешено, gRPC в `grpc/`.
3. Откройте pull request из своей ветки fork в ветку `seminar/06-rest-api-development` основного репозитория.
4. В описании PR укажите ФИО, что реализовано (REST, gRPC) и предметную область сервиса.

**Критерий успешной сдачи PR: весь CI зелёный.** Для REST-only работы — зелёные jobs «Структура PR» и «REST», gRPC пропускается. Для работы с gRPC — зелёные все три.

> [!note]
> Для первого PR из fork GitHub может попросить преподавателя подтвердить запуск workflow. Если CI долго в статусе ожидания, это нормально.

## Баллы и дедлайн

| Часть | Максимум |
|---|---|
| REST | 5 баллов |
| gRPC | 4 балла — по баллу за каждый тип взаимодействия, если сможете объяснить, как и для чего он |

- За каждую нерабочую деталь — минус 0,5 балла.
- PR до начала следующей лекции по API — +1 балл (отдельно для REST и gRPC).
- Защита до начала лекции или сразу после неё — ещё +1 балл.
- Вопросы на защите любые: какие методы, что такое FastAPI, почему код написан именно так.

**Дедлайн: `2026-10-15 08:59:50` (МСК).** До дедлайна должен быть открыт PR в `seminar/06-rest-api-development`. Пересдачи нет.
