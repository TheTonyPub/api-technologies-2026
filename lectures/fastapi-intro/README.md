# Лекция: REST API на FastAPI

Материалы лекции: за полтора часа мы с нуля написали сервис **Task Tracker** (CRUD задач) на FastAPI и дошли до роутеров, middleware и CORS.

- [`KONSPEKT.md`](KONSPEKT.md) — конспект лекции: теория, код каждого шага, шпаргалка и вопросы для самопроверки. Оформлен для Obsidian: файл можно положить в своё хранилище, там отрисуются схемы и раскрывающиеся ответы.
- [`steps/`](steps) — готовый код после каждого шага лекции.
- [`cors-demo/`](cors-demo) — страница для проверки CORS из браузера.

## Шаги

| Папка | Что внутри |
|---|---|
| [`steps/01_hello`](steps/01_hello/main.py) | минимальное приложение, `/` и `/health` |
| [`steps/02_params`](steps/02_params/main.py) | path- и query-параметры, `Path` и `Query` |
| [`steps/03_models`](steps/03_models/main.py) | Pydantic: `BaseModel`, `Field`, `Enum`, `response_model` |
| [`steps/04_crud`](steps/04_crud/main.py) | полный CRUD на словаре, 404, `model_validator` |
| [`steps/05_routers`](steps/05_routers) | то же, разнесённое по `schemas.py`, `storage.py`, `routers/` |
| [`steps/06_middleware_cors`](steps/06_middleware_cors) | логирующий middleware и `CORSMiddleware` |

## Как запустить

Команды вводятся в терминале из корня репозитория.

```sh
# перейти в папку лекции
cd lectures/fastapi-intro

# создать и включить виртуальное окружение
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1

# установить зависимости
pip install -r requirements.txt

# запустить нужный шаг, например CRUD
cd steps/04_crud
uvicorn main:app --reload
```

Пока сервис запущен, документация открывается по адресу http://localhost:8000/docs: там можно вызвать каждый метод кнопкой «Try it out». Остановить сервис — `Ctrl+C`.

## Демо CORS

1. Запустите шаг 6: `cd steps/06_middleware_cors && uvicorn main:app --reload`.
2. Во втором терминале запустите страницу: `cd cors-demo && python -m http.server 5500`.
3. Откройте http://localhost:5500 и нажмите кнопки. Чтобы увидеть ошибку CORS, закомментируйте `app.add_middleware(CORSMiddleware, ...)` в `main.py` шага 6 и посмотрите в консоль браузера.

## Что попробовать самостоятельно

- Переделать изменение задачи с `PUT` на `PATCH`.
- Вынести пагинацию списка в зависимость `Depends` (пример в разделе 10 конспекта).
- Добавить второй ресурс, например проекты, со своим роутером, и привязать к ним задачи.
