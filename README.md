# API-технологии — код курса

Приватный student-facing репозиторий исполняемых примеров, starter-проектов и публичных проверок курса «API-технологии».

## Как выбрать материал

Каждая учебная единица находится в отдельной автономной ветке:

| Материал | Ветка | Scope |
|---|---|---|
| Лекция 1 | `lecture/01-api-interface-layer` | `COMMON` + `PRB`/`SII` |
| Лекция 2 | `lecture/02-http-rest-openapi` | `COMMON` + `PRB`/`SII` |
| Лекция 3 | `lecture/03-integration-styles` | `COMMON` + `PRB`/`SII` |
| Лекция 4 | `lecture/04-fastapi-services` | `COMMON` + `PRB`/`SII` |
| ПР 1, семинар 1 и ДЗ 1 | `seminar/01-api-scenarios` | `PRB` или `SII` |
| ПР 2, семинар 2 и ДЗ 2 | `seminar/02-rest-openapi-contract` | `PRB` или `SII` |
| ПР 3, семинар 3 и ДЗ 3 | `seminar/03-http-diagnostics` | `PRB` или `SII` |
| ПР 4, семинар 4 и ДЗ 4 | `seminar/04-integration-style-selection` | `PRB` или `SII` |
| ПР 5, семинары 5–6 и ДЗ 5 | `seminar/05-fastapi-service` | `PRB` или `SII` |

Пример получения одной ветки:

```bash
git clone --branch seminar/05-fastapi-service --single-branch git@github.com:TheTonyPub/api-technologies-code.git
```

## Практика и домашнее продолжение

Практическая работа и ДЗ с тем же номером выполняются в одной рабочей ветке студента и в одном будущем pull request. Отдельный проект или ветка `homework/*` не создаётся. В README конкретной `seminar/*` ветки отдельно обозначены этапы «на занятии» и «дома».

## Профили

- `COMMON` — общий контрактный материал двух профилей.
- `PRB` — «Программные решения для бизнеса».
- `SII` — «Системы искусственного интеллекта».

Если ветка содержит два профильных пути, выберите ровно один и не смешивайте обязательные результаты разных РПД.

## Безопасность

Используйте только localhost, синтетические данные и фиктивные значения. Не добавляйте credentials, персональные данные, production endpoints, `.env`, виртуальные окружения или generated artifacts.

