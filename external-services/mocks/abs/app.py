"""Мок АБС (автоматизированной банковской системы). Путь на сервере: /abs."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, Path, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..common import bank, companies
from ..common.core import ApiError, RateLimiter, create_app, page, require_team, rng_for

CASES = (
    "\n\n**Кому нужен.** Кейс «Антифрод»: клиенты, счета, история операций (ETL в Data Lake и агрегаты "
    "в Redis), поток новых операций для проверки через свой Gateway. Кейс «СПАРК»: признак «клиент банка» "
    "по ИНН для Enrichment Service."
)

app = create_app(
    "Мок АБС",
    "Автоматизированная банковская система вымышленного банка: физлица, счета, операции и юрлица-клиенты."
    + CASES,
    tags=[
        {"name": "clients", "description": "Клиенты банка. Кейсы: Антифрод (физлица), СПАРК (юрлица)."},
        {"name": "accounts", "description": "Счета. Кейс: Антифрод."},
        {"name": "transactions", "description": "История и поток операций. Кейс: Антифрод."},
        {"name": "legal-clients", "description": "Юрлица — клиенты банка по ИНН. Кейс: СПАРК (isBankClient)."},
    ],
)
limiter = RateLimiter(int(os.getenv("ABS_RPS", "20")))
MAX_RANGE = timedelta(days=31)


def team(request: Request, t: str = Depends(require_team)) -> str:
    limiter.check(t)
    return t


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------- схемы

class AccountOut(BaseModel):
    account_id: str = Field(examples=["acc-0000001"])
    client_id: str
    number: str = Field(description="Номер счёта (вымышленный)")
    currency: Literal["RUB", "USD", "EUR"]
    opened_at: date
    status: Literal["active", "closed"]


class ClientOut(BaseModel):
    client_id: str = Field(examples=["cl-000001"])
    type: Literal["individual"] = "individual"
    full_name: str
    birth_date: date
    gender: Literal["male", "female"]
    home_region_code: str = Field(description="Код региона проживания по данным банка")
    customer_since: date
    segment: Literal["mass", "affluent", "premium"]
    phone_masked: str
    accounts: list[str]


class LegalClientOut(BaseModel):
    inn: str = Field(examples=["7701234567"])
    short_name: str
    client_since: date
    segment: Literal["small", "medium", "corporate"]
    products: list[Literal["settlement_account", "salary_project", "acquiring", "credit_line", "deposit"]]
    is_bank_client: Literal[True] = True


class LiveTxOut(BaseModel):
    transaction_id: str = Field(examples=["tx-20261001-0000001-00"])
    account_id: str
    client_id: str
    amount: float = Field(gt=0)
    currency: Literal["RUB", "USD", "EUR"]
    timestamp: datetime
    merchant_id: str | None = Field(description="Мерчант (для card/online). Риск — в /client-data")
    mcc: str | None = Field(description="Код категории продавца; 6011 — снятие в банкомате")
    channel: Literal["card", "online", "transfer", "atm"]
    region_code: str = Field(description="Регион, где совершена операция")
    counterparty_account: str | None = Field(description="Счёт получателя для переводов")


class TxOut(LiveTxOut):
    is_fraud: bool = Field(description="Подтверждённый фрод")


class Page(BaseModel):
    items: list
    nextCursor: str | None


class ClientPage(Page):
    items: list[ClientOut | LegalClientOut]


class TxPage(Page):
    items: list[TxOut]


class LiveTxPage(Page):
    items: list[LiveTxOut]


class LookupIn(BaseModel):
    inns: list[str] = Field(min_length=1, max_length=500, examples=[["7701234567", "5012345678"]])


class LookupItem(BaseModel):
    inn: str
    is_bank_client: bool
    client: LegalClientOut | None


class LookupOut(BaseModel):
    items: list[LookupItem]


class LabelOut(BaseModel):
    transaction_id: str
    is_fraud: bool
    labeled_at: datetime


# ---------------------------------------------------------------- преобразования

def client_out(c: bank.Client) -> dict:
    _, accounts = bank.clients_and_accounts()
    return {"client_id": c.client_id, "type": "individual", "full_name": c.full_name,
            "birth_date": c.birth_date, "gender": c.gender, "home_region_code": c.home_region,
            "customer_since": c.customer_since, "segment": c.segment, "phone_masked": c.phone_masked,
            "accounts": [accounts[a].account_id for a in c.accounts]}


def legal_out(idx: int) -> dict:
    comp = companies.universe()[0][idx]
    r = rng_for("legal-client", idx)
    since = max(comp.registration_date, date(2005, 1, 1)) + timedelta(days=r.randint(30, 2500))
    since = min(since, date(2026, 8, 1))
    segment = "corporate" if comp.employees > 500 else ("medium" if comp.employees > 50 else "small")
    products = ["settlement_account"] + [p for p in ["salary_project", "acquiring", "credit_line", "deposit"]
                                         if r.random() < 0.35]
    return {"inn": comp.inn, "short_name": comp.short_name, "client_since": since, "segment": segment,
            "products": products, "is_bank_client": True}


def legal_clients() -> list[int]:
    flags = companies.bank_client_flags()
    return [i for i, f in sorted(flags.items()) if f]


def tx_out(t: bank.Tx, with_label=True) -> dict:
    return t.as_dict(with_label)


def parse_cursor(cursor: str | None, n_parts: int) -> list[str] | None:
    if cursor is None:
        return None
    parts = cursor.split(":")
    if len(parts) != n_parts:
        raise ApiError(400, "INVALID_REQUEST", "Неверный cursor")
    return parts


# ---------------------------------------------------------------- клиенты

@app.get("/v1/clients", tags=["clients"], response_model=ClientPage,
         summary="Список клиентов банка",
         description="Кейс Антифрод: `type=individual` — физлица для первичной загрузки профилей. "
                     "Кейс СПАРК: `type=legal` — все юрлица-клиенты банка.")
def list_clients(t: str = Depends(team), type: Literal["individual", "legal"] = "individual",
                 limit: int = Query(100, ge=1, le=500), cursor: str | None = None):
    start = int(cursor) if cursor and cursor.isdigit() else 0
    if type == "individual":
        cl, _ = bank.clients_and_accounts()
        chunk = [client_out(c) for c in cl[start:start + limit]]
        total = len(cl)
    else:
        ids = legal_clients()
        chunk = [legal_out(i) for i in ids[start:start + limit]]
        total = len(ids)
    nxt = str(start + limit) if start + limit < total else None
    return page(chunk, nxt)


@app.get("/v1/clients/{client_id}", tags=["clients"], response_model=ClientOut,
         summary="Карточка физлица", description="Кейс Антифрод: профиль клиента и его счета.")
def get_client(client_id: str = Path(examples=["cl-000001"]), t: str = Depends(team)):
    c = bank.client_by_id(client_id)
    if not c:
        raise ApiError(404, "CLIENT_NOT_FOUND", f"Клиент {client_id} не найден")
    return client_out(c)


@app.get("/v1/legal-clients/{inn}", tags=["legal-clients"], response_model=LegalClientOut,
         summary="Юрлицо — клиент банка?",
         description="Кейс СПАРК: Enrichment Service проставляет `isBankClient`. 200 — клиент, "
                     "404 `NOT_A_CLIENT` — компания не обслуживается в банке.")
def get_legal_client(inn: str = Path(pattern=r"^\d{10}$", examples=["7701234567"]), t: str = Depends(team)):
    idx = companies.universe()[2].get(inn)
    if idx is None or not companies.bank_client_flags()[idx]:
        raise ApiError(404, "NOT_A_CLIENT", f"Компания с ИНН {inn} не клиент банка")
    return legal_out(idx)


@app.post("/v1/legal-clients:lookup", tags=["legal-clients"], response_model=LookupOut,
          summary="Пакетная проверка ИНН (до 500)",
          description="Кейс СПАРК: то же, что `GET /v1/legal-clients/{inn}`, но пачкой, чтобы обогащение "
                      "не делало сотни вызовов.")
def lookup_legal(body: LookupIn, t: str = Depends(team)):
    _, _, by_inn = companies.universe()
    flags = companies.bank_client_flags()
    items = []
    for inn in body.inns:
        idx = by_inn.get(inn)
        ok = idx is not None and flags[idx]
        items.append({"inn": inn, "is_bank_client": ok, "client": legal_out(idx) if ok else None})
    return {"items": items}


# ---------------------------------------------------------------- счета

@app.get("/v1/accounts/{account_id}", tags=["accounts"], response_model=AccountOut,
         summary="Счёт", description="Кейс Антифрод: по `account_id` из транзакции найти владельца.")
def get_account(account_id: str = Path(examples=["acc-0000001"]), t: str = Depends(team)):
    a = bank.account_by_id(account_id)
    if not a:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", f"Счёт {account_id} не найден")
    cl, _ = bank.clients_and_accounts()
    return {"account_id": a.account_id, "client_id": cl[a.client_idx].client_id, "number": a.number,
            "currency": a.currency, "opened_at": a.opened_at, "status": a.status}


# ---------------------------------------------------------------- транзакции

def _range(from_: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    n = now()
    end = min(to or n, n)
    start = from_ or end - timedelta(days=1)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    lo, _ = bank.history_bounds(n)
    start = max(start, lo)
    if end - start > MAX_RANGE:
        raise ApiError(400, "INVALID_REQUEST", "Интервал from..to не больше 31 дня")
    if start >= end:
        raise ApiError(400, "INVALID_REQUEST", "from должен быть раньше to (и не в будущем)")
    return start, end


@app.get("/v1/transactions", tags=["transactions"], response_model=TxPage,
         summary="История операций с меткой фрода",
         description="Кейс Антифрод: ETL выгружает историю в Data Lake и считает агрегаты для Redis "
                     "(`avg_amount_30d`, `tx_count_24h`). История — последние 365 дней, интервал за один "
                     "запрос — до 31 дня, по умолчанию последние сутки. Сортировка: день (по Москве), "
                     "счёт, время.")
def list_transactions(t: str = Depends(team), from_: datetime | None = Query(None, alias="from"),
                      to: datetime | None = None, account_id: str | None = None,
                      limit: int = Query(100, ge=1, le=500), cursor: str | None = None):
    start, end = _range(from_, to)
    _, accounts = bank.clients_and_accounts()
    if account_id:
        acc = bank.account_by_id(account_id)
        if not acc:
            raise ApiError(404, "ACCOUNT_NOT_FOUND", f"Счёт {account_id} не найден")
        acc_range = [acc.idx]
    else:
        acc_range = range(len(accounts))
    cur = parse_cursor(cursor, 3)
    day = date.fromisoformat(cur[0]) if cur else bank.msk_day(start)
    first_acc = int(cur[1]) if cur else 0
    skip = int(cur[2]) if cur else 0
    out: list[dict] = []
    last_day = bank.msk_day(end)
    while day <= last_day:
        for a in acc_range:
            if a < first_acc:
                continue
            txs = [x for x in bank.account_day(a, day) if start <= x.timestamp < end]
            for n, x in enumerate(txs):
                if n < skip:
                    continue
                if len(out) == limit:
                    return page(out, f"{day.isoformat()}:{a}:{n}")
                out.append(tx_out(x))
            skip = 0
        first_acc = 0
        day += timedelta(days=1)
    return page(out, None)


@app.get("/v1/exports/transactions/{export_date}", tags=["transactions"],
         summary="Выгрузка операций за день (NDJSON)",
         description="Кейс Антифрод: пакетная выгрузка для Airflow — все операции за календарный день "
                     "по Москве, по одной JSON-записи на строку. Сегодня и будущие даты — 404 "
                     "`EXPORT_NOT_READY`: выгрузка готова на следующий день.",
         response_class=StreamingResponse,
         responses={200: {"content": {"application/x-ndjson": {}}}})
def export_day(export_date: date, t: str = Depends(team)):
    n = now()
    if export_date >= bank.msk_day(n):
        raise ApiError(404, "EXPORT_NOT_READY", f"Выгрузка за {export_date} ещё не готова")
    lo, _ = bank.history_bounds(n)
    if export_date < bank.msk_day(lo):
        raise ApiError(404, "EXPORT_NOT_FOUND", "Выгрузки хранятся 365 дней")
    _, accounts = bank.clients_and_accounts()

    def gen():
        for a in range(len(accounts)):
            for x in bank.account_day(a, export_date):
                yield json.dumps(tx_out(x), ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": f'attachment; filename="transactions-{export_date}.ndjson"'})


@app.get("/v1/transactions/live", tags=["transactions"], response_model=LiveTxPage,
         summary="Поток новых операций (без метки)",
         description="Кейс Антифрод: так АБС «видит» новые операции. Команда забирает их и отправляет "
                     "в свой Gateway (`POST /v1/transactions/evaluate`), как это делала бы АБС. "
                     "Каждую минуту появляется 60 операций, доступны последние 10 минут. "
                     "Без `after` возвращаются самые свежие `limit` операций. Чтобы читать поток без пропусков, передавайте `after` = последний полученный "
                     "`transaction_id`. Метки нет: её можно узнать через 5 минут в `/label`.")
def live(t: str = Depends(team), after: str | None = None, limit: int = Query(50, ge=1, le=500)):
    n = now()
    cur_min = int(n.timestamp()) // 60
    first_min = cur_min - 9
    after_min, after_n = None, -1
    if after:
        try:
            _, _, m, k = after.split("-")
            after_min, after_n = int(m), int(k)
        except ValueError:
            raise ApiError(400, "INVALID_REQUEST", "after должен быть transaction_id вида tx-live-<минута>-<номер>")
    out = []
    for m in range(max(first_min, after_min or first_min), cur_min + 1):
        for x in bank.live_minute(m):
            k = int(x.transaction_id.rsplit("-", 1)[1])
            if after_min is not None and (m < after_min or (m == after_min and k <= after_n)):
                continue
            if x.timestamp > n:
                break
            if after and len(out) == limit:
                return page(out, out[-1]["transaction_id"])
            out.append(tx_out(x, with_label=False))
    if not after:
        out = out[-limit:]  # без after — самые свежие операции
    return page(out, out[-1]["transaction_id"] if out else after)


@app.get("/v1/transactions/{transaction_id}/label", tags=["transactions"], response_model=LabelOut,
         summary="Истинная метка операции",
         description="Кейс Антифрод: проверить свой вердикт. Для live-операций метка появляется через "
                     "5 минут (до этого 404 `LABEL_NOT_READY`), для истории — сразу.")
def label(transaction_id: str, t: str = Depends(team)):
    parts = transaction_id.split("-")
    n = now()
    if transaction_id.startswith("tx-live-") and len(parts) == 4:
        m, k = int(parts[2]), int(parts[3])
        batch = bank.live_minute(m)
        when = datetime.fromtimestamp(m * 60, tz=timezone.utc) + timedelta(minutes=1) + bank.LABEL_DELAY
        if k >= len(batch) or batch[k].timestamp > n:
            raise ApiError(404, "TRANSACTION_NOT_FOUND", "Операция не найдена")
        if n < when:
            raise ApiError(404, "LABEL_NOT_READY", f"Метка будет доступна после {bank.iso(when)}",
                           headers={"Retry-After": str(int((when - n).total_seconds()) + 1)})
        return {"transaction_id": transaction_id, "is_fraud": batch[k].is_fraud, "labeled_at": when}
    if len(parts) == 4 and parts[0] == "tx":
        try:
            d = datetime.strptime(parts[1], "%Y%m%d").date()
            a, k = int(parts[2]) - 1, int(parts[3])
            if a < 0 or k < 0:
                raise ValueError
            txs = bank.account_day(a, d)
            x = txs[k]
        except (ValueError, IndexError):
            raise ApiError(404, "TRANSACTION_NOT_FOUND", "Операция не найдена")
        if x.timestamp > n:
            raise ApiError(404, "TRANSACTION_NOT_FOUND", "Операция не найдена")
        return {"transaction_id": transaction_id, "is_fraud": x.is_fraud, "labeled_at": x.timestamp}
    raise ApiError(404, "TRANSACTION_NOT_FOUND", "Операция не найдена")
