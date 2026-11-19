# Савелий · Client Info и Gateway

Распакуй архив в корень существующего репозитория на ветке `homework/04-api-services`.
Проверено с базовым коммитом `3797892`. Папки внутри ZIP начинаются с корня репозитория.

## Запуск тестов

Из корня проекта с Python 3.11 или новее выполни в PowerShell.

```powershell
python -m pip install -r services/client-info/requirements.txt -r services/gateway/requirements.txt
python -m unittest discover -s services/client-info/tests -v
```

Тесты проходят через ASGI-приложение Gateway и целевой сервис. Подключения к PostgreSQL и Redis
подменяются в тестах. Для этих сценариев Docker, СПАРК и АБС не требуются.
