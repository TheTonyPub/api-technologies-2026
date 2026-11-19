# Изменения архитектуры и контрактов в ДЗ 4

| Что | Было (ДЗ 1–2) | Стало (ДЗ 4) | Почему |
|---|---|---|---|
| Scoring → ML Model | REST (`contracts/ml-model/openapi.yaml`, `POST /v1/predictions`) | gRPC (`proto/scoring.proto`) | требование задания; REST-контракт ML Model заменён `.proto` |
| Enrichment → АБС | не было связи на диаграмме | REST `/abs/v1/legal-clients:lookup` пачками до 500 ИНН | источник `isBankClient` |
| Аналитический контур | в архитектуре | не реализуется в ДЗ 4 | явно исключён заданием |
| Признак `groupBankClientsCount` | «компаний группы — клиенты банка» | число **других** компаний группы, клиентов банка (без самой компании) | так определено в `meta["feature_doc"]` модели |
| Версия модели в примерах | `lead-scoring-2026.09.1` | `company-scoring`, `1.0.0` | реальная модель из задания |
| Карточка компании | Заголовок кэша отсутствовал | `X-Cache: HIT` или `MISS` в Client Info и Gateway | позволяет проверить cache-aside |
| Роль участника группы | Только `PARENT`, `SUBSIDIARY`, `AFFILIATE` | Допускается `relation: null` | чтобы вернуть компанию с известной группой, когда СПАРК не отдал её роль |
| События об изменениях | Связь с брокером отсутствовала | PostgreSQL outbox и Go-приложения для `company.changes` и `company.audit` | дополнительное задание |

Актуальные исходники и PNG находятся в [architecture](../architecture).
`contracts/ml-model/openapi.yaml` сохранён как исторический контракт ДЗ 2.
