# ДЗ 4. Реализация сервисов для кейса СПАРК

Актуальный запуск, порты, архитектура и порядок приёмки собраны в [корневом README](../README.md).
Правила совместной работы находятся в [WORKFLOW](WORKFLOW.md), критерии сдачи — в [ТЗ](TechSpec.md#8-что-проверить-перед-сдачей).

## Соответствие требованиям

| Требование | Реализация | Как проверить |
|---|---|---|
| Запуск стека одной командой | [Docker Compose](../docker-compose.yml) с healthcheck, миграциями PostgreSQL, брокером и Go-продьюсером | `docker compose up -d --build --wait` |
| Авторизация СПАРК, SOAP, пагинация, первичная и повторная загрузка | [SOAP-клиент](../services/loader/app/soap_client.py), [Loader](../services/loader/app/loader.py) и [инкремент](../services/loader/app/incremental.py) | `GET /status`, `POST /sync`, пять сценариев сбоев из `.env.example` |
| История SCD2, идемпотентность и сохранность данных | [SCD2](../services/loader/app/scd2.py), [миграции](../db/migrations), [API истории](../services/enrichment/app/history.py) | История до и после изменения, повторный `/sync`, проверка счётчиков после перезапуска |
| Пакетная проверка АБС, витрина и прогрев Redis | [АБС-клиент](../services/enrichment/app/abs_client.py), [Enrichment](../services/enrichment/app/pipeline.py) | `GET /status` Enrichment, 1000 карточек и 451 клиент банка на контрольном наборе |
| Карточка компании, TTL кэша и чтение из БД при сбое Redis | [Client Info](../services/client-info/app/repository.py), [тесты Савелия](../services/client-info/tests/test_gateway_contract.py) | `MISS → HIT`, остановка Redis, ответ `404` для неизвестного ИНН |
| Состав группы и фильтр клиентов банка | [Group Companies](../services/group-companies/app/repository.py), [тесты Павла](../services/group-companies/tests/test_gateway_contract.py) | Сравнение `/group` и `/group?onlyBankClients=true` |
| Gateway, Bearer, валидация, единые ошибки и трассировка | [Gateway](../services/gateway/app/main.py), [обработка ошибок](../libs/common/platform_common/errors.py), [вызов нижних сервисов](../libs/common/platform_common/upstream.py) | Проверки `400`, `401`, `404`, `503`, `504` и `X-Request-Id` |
| Скоринг по gRPC и сверка с моделью | [Scoring](../services/scoring/app/features.py), [gRPC-контракт](../proto/scoring.proto), [ML Model](../services/ml-model/app/server.py) | [Прямое сравнение прогноза](../scripts/check_scoring.py) для трёх ИНН |
| Приёмка одним сценарием и отчёт | [demo.sh](../scripts/demo.sh) и [инструкция](../README.md#проверка-перед-сдачей) | `--acceptance` и `demo-result.json`, включая счётчики 1000 / 73 / 451 и эталон новых версий |
| Документация, контракты и вклад команды | [README](../README.md), [диаграммы](../architecture), [OpenAPI](../contracts), [изменения контрактов](CHANGES-hw4.md) | `git lfs ls-files`, история коммитов, отсутствие `.env` и `.dill` в Git, PR в одноимённую ветку основного репозитория |
| Дополнительно: метрики, дашборд и трассировка | [Метрики Loader](../services/loader/app/metrics.py), [Prometheus и Grafana](../compose.monitoring.yml), [REST middleware](../libs/common/platform_common/errors.py) | Таргет Loader, дашборд «СПАРК · Loader» и совпадающий `X-Request-Id` в логах Gateway и нижнего сервиса |
| Дополнительно: тесты и CI | [GitHub Actions](../.github/workflows/ci.yml), [локальный запуск](WORKFLOW.md#тесты) | Ruff, actionlint, Bash, Python-тесты, `go test`, `go vet`, проверка Compose и сборка образов |
| Дополнительно: события изменений | [Транзакционный outbox](../db/migrations/002_company_outbox.sql), [Kafka и Go](../services/company-events/README.md) | Новая версия → `company.changes` → `company.audit`, отмена и коммит транзакции Kafka |
