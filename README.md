# Семинар 1: Сценарии использования API

Ветка: `seminar/01-api-scenarios`. Выберите профиль `profiles/prb` или `profiles/sii`; не смешивайте артефакты профилей.

## Этап 1 — на занятии

Работайте в `profiles/<profile>/practical/starter` и сверяйтесь с `profiles/<profile>/practical/public-checks`.

## Этап 2 — дома

Продолжайте ту же Git-ветку и выполните задание из `profiles/<profile>/homework/starter`. Отдельная `homework/*` ветка не создаётся. Для работы студента используется его приватный fork/репозиторий; сдача фиксируется последним commit в PR/MR его репозитория.

## Окружение и запуск

Для Python-заданий нужен Python 3.12+. Если в корне есть `requirements.txt`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Читайте профильные README в `public-checks`. Публичная проверка для задания 5:

```bash
pytest -q profiles/<profile>/practical/public-checks
```

До выполнения TODO часть student checks может ожидаемо падать. Все примеры данных синтетические; реальные endpoint, ключи и персональные данные добавлять нельзя.
