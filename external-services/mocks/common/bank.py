"""Банк: физлица, счета, мерчанты, риски регионов и транзакции.

Общий источник для /abs (клиенты, счета, транзакции), /client-data (демография, риски) и
для обучения модели антифрода. Транзакции счёта за день считаются из (SEED, счёт, день),
поэтому их не нужно хранить: любой запрос даёт тот же результат.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from . import reference as ref
from .core import rng_for

N_CLIENTS = 2000
N_MERCHANTS = 600
HISTORY_DAYS = 365
COMPROMISED_DAY_PROB = 0.004  # шанс, что в этот день счёт скомпрометирован и по нему идёт фрод
LIVE_PER_MINUTE = 60
LIVE_FRAUD_ACCOUNT_PROB = 0.02
LABEL_DELAY = timedelta(minutes=5)
MSK = timedelta(hours=3)


@dataclass(frozen=True)
class Client:
    idx: int
    client_id: str
    full_name: str
    gender: str  # male | female
    birth_date: date
    home_region: str
    customer_since: date
    segment: str  # mass | affluent | premium
    phone_masked: str
    typical_amount: float
    activity: float  # среднее число операций в день на счёт
    accounts: tuple[int, ...]


@dataclass(frozen=True)
class Account:
    idx: int
    account_id: str
    client_idx: int
    number: str
    currency: str
    opened_at: date
    status: str


@dataclass(frozen=True)
class Merchant:
    idx: int
    merchant_id: str
    name: str
    mcc: str
    region: str
    risk: float
    last_complaint: date | None


@dataclass(frozen=True)
class Tx:
    transaction_id: str
    account_id: str
    client_id: str
    amount: float
    currency: str
    timestamp: datetime
    merchant_id: str | None
    mcc: str | None
    channel: str
    region_code: str
    counterparty_account: str | None
    is_fraud: bool

    def as_dict(self, with_label: bool = True) -> dict:
        d = {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "client_id": self.client_id,
            "amount": self.amount,
            "currency": self.currency,
            "timestamp": iso(self.timestamp),
            "merchant_id": self.merchant_id,
            "mcc": self.mcc,
            "channel": self.channel,
            "region_code": self.region_code,
            "counterparty_account": self.counterparty_account,
        }
        if with_label:
            d["is_fraud"] = self.is_fraud
        return d


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _account_number(r, currency: str) -> str:
    code = {"RUB": "810", "USD": "840", "EUR": "978"}[currency]
    return f"40817{code}{r.randint(0, 999999999999):012d}"


@lru_cache(maxsize=1)
def clients_and_accounts() -> tuple[list[Client], list[Account]]:
    clients: list[Client] = []
    accounts: list[Account] = []
    for i in range(N_CLIENTS):
        r = rng_for("client", i)
        gender = "male" if r.random() < 0.48 else "female"
        if gender == "male":
            name = f"{r.choice(ref.SURNAMES)} {r.choice(ref.MALE_FIRST)} {r.choice(ref.MALE_PATRONYMIC)}"
        else:
            name = (f"{ref.female_surname(r.choice(ref.SURNAMES))} {r.choice(ref.FEMALE_FIRST)} "
                    f"{r.choice(ref.FEMALE_PATRONYMIC)}")
        age_days = int(r.uniform(18, 80) * 365.25)
        birth = date(2026, 9, 1) - timedelta(days=age_days)
        since = date(2008, 1, 1) + timedelta(days=r.randint(0, (date(2025, 6, 30) - date(2008, 1, 1)).days))
        segment = r.choices(["mass", "affluent", "premium"], weights=[80, 15, 5])[0]
        typical = math.exp(r.gauss(math.log(1500), 0.6)) * {"mass": 1, "affluent": 2.5, "premium": 6}[segment]
        n_acc = 1 if r.random() < 0.5 else 2
        acc_ids = []
        for _ in range(n_acc):
            a_idx = len(accounts)
            cur = "RUB" if r.random() < 0.94 else r.choice(["USD", "EUR"])
            opened = since + timedelta(days=r.randint(0, max(1, (date(2025, 8, 31) - since).days)))
            accounts.append(Account(idx=a_idx, account_id=f"acc-{a_idx + 1:07d}", client_idx=i,
                                    number=_account_number(r, cur), currency=cur, opened_at=opened,
                                    status="active"))
            acc_ids.append(a_idx)
        clients.append(Client(
            idx=i, client_id=f"cl-{i + 1:06d}", full_name=name, gender=gender, birth_date=birth,
            home_region=r.choices(ref.REGION_CODES, weights=ref.REGION_WEIGHTS)[0],
            customer_since=since, segment=segment,
            phone_masked=f"+7 9{r.randint(0, 99):02d} ***-**-{r.randint(0, 99):02d}",
            typical_amount=round(typical, 2), activity=r.uniform(0.25, 1.1), accounts=tuple(acc_ids),
        ))
    return clients, accounts


def client_by_id(client_id: str) -> Client | None:
    if not (client_id.startswith("cl-") and client_id[3:].isdigit()):
        return None
    i = int(client_id[3:]) - 1
    cl, _ = clients_and_accounts()
    return cl[i] if 0 <= i < len(cl) else None


def account_by_id(account_id: str) -> Account | None:
    if not (account_id.startswith("acc-") and account_id[4:].isdigit()):
        return None
    i = int(account_id[4:]) - 1
    _, acc = clients_and_accounts()
    return acc[i] if 0 <= i < len(acc) else None


# ---------------------------------------------------------------- риски (данные бюро для /client-data)

@lru_cache(maxsize=None)
def region_risk(code: str) -> float:
    r = rng_for("region-risk", code)
    if code in ref.HIGH_RISK_REGIONS:
        return round(r.uniform(0.6, 0.85), 3)
    return round(r.uniform(0.03, 0.3), 3)


def risk_category(x: float) -> str:
    return "high" if x >= 0.6 else ("medium" if x >= 0.3 else "low")


@lru_cache(maxsize=1)
def merchants() -> list[Merchant]:
    out = []
    weights = [30, 14, 10, 10, 8, 8, 6, 4, 2, 3, 1.5, 1.5, 2]
    for i in range(N_MERCHANTS):
        r = rng_for("merchant", i)
        mcc = r.choices(ref.MCC_CODES, weights=weights)[0]
        base = ref.MCC[mcc][1]
        risk = min(0.98, max(0.01, base + r.gauss(0, 0.07)))
        region = r.choices(ref.REGION_CODES, weights=ref.REGION_WEIGHTS)[0]
        complaint = None
        if r.random() < risk:
            complaint = date(2026, 9, 1) - timedelta(days=r.randint(1, 400))
        name = f"{r.choice(ref.NAME_WORDS_A)} {r.choice(ref.NAME_WORDS_B)}"
        out.append(Merchant(idx=i, merchant_id=f"m-{i + 1:05d}", name=name, mcc=mcc, region=region,
                            risk=round(risk, 3), last_complaint=complaint))
    return out


@lru_cache(maxsize=1)
def _merchant_pools():
    ms = merchants()
    safe = [m for m in ms if m.risk < 0.3]
    risky = [m for m in ms if m.risk >= 0.5]
    safe_by_region: dict[str, list[Merchant]] = {}
    for m in safe:
        safe_by_region.setdefault(m.region, []).append(m)
    return safe, risky, safe_by_region


def merchant_by_id(mid: str) -> Merchant | None:
    if not (mid.startswith("m-") and mid[2:].isdigit()):
        return None
    i = int(mid[2:]) - 1
    ms = merchants()
    return ms[i] if 0 <= i < len(ms) else None


# ---------------------------------------------------------------- транзакции

def _poisson(r, lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= l:
            return k
        k += 1


def _normal_tx(r, client: Client, acc: Account, day_start: datetime, n: int, prefix: str,
               fraud: bool) -> Tx:
    safe, risky, safe_by_region = _merchant_pools()
    _, accounts = clients_and_accounts()
    if fraud:
        local_hour = r.choice([0, 1, 2, 3, 4, 5]) if r.random() < 0.7 else r.randint(6, 23)
        amount = client.typical_amount * r.uniform(4, 20)
        if r.random() < 0.6:
            region = r.choice(sorted(ref.HIGH_RISK_REGIONS - {client.home_region}))
        else:
            region = r.choice([c for c in ref.REGION_CODES if c != client.home_region])
        channel = r.choices(["online", "transfer", "card", "atm"], weights=[45, 35, 15, 5])[0]
        merchant = r.choice(risky) if r.random() < 0.7 else r.choice(safe)
    else:
        local_hour = min(23, max(6, int(r.gauss(14, 4)))) if r.random() > 0.03 else r.randint(0, 5)
        amount = client.typical_amount * math.exp(r.gauss(0, 0.6))
        channel = r.choices(["card", "online", "transfer", "atm"], weights=[60, 25, 10, 5])[0]
        if r.random() < 0.9:
            region = client.home_region
            merchant = r.choice(safe_by_region.get(region) or safe)
        else:
            merchant = r.choice(safe) if r.random() < 0.97 else r.choice(risky)
            region = merchant.region
    ts = day_start + timedelta(hours=local_hour, seconds=r.randint(0, 3599)) - MSK
    counterparty = None
    m_id, mcc = merchant.merchant_id, merchant.mcc
    if channel == "transfer":
        counterparty = accounts[r.randrange(len(accounts))].account_id
        m_id, mcc = None, None
    elif channel == "atm":
        m_id, mcc = None, "6011"
    if acc.currency != "RUB":
        amount = amount / (90 if acc.currency == "USD" else 100)
    return Tx(transaction_id=f"{prefix}-{n:02d}", account_id=acc.account_id, client_id=client.client_id,
              amount=round(max(amount, 10 if acc.currency == "RUB" else 1), 2), currency=acc.currency,
              timestamp=ts, merchant_id=m_id, mcc=mcc, channel=channel, region_code=region,
              counterparty_account=counterparty, is_fraud=fraud)


@lru_cache(maxsize=200_000)
def account_day(acc_idx: int, day: date) -> tuple[Tx, ...]:
    """Все операции счёта за календарный день (по Москве), отсортированные по времени."""
    clients, accounts = clients_and_accounts()
    acc = accounts[acc_idx]
    if day < acc.opened_at:
        return ()
    client = clients[acc.client_idx]
    r = rng_for("tx", acc_idx, day.isoformat())
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    prefix = f"tx-{day.strftime('%Y%m%d')}-{acc_idx + 1:07d}"
    items = [_normal_tx(r, client, acc, day_start, 0, prefix, False) for _ in range(_poisson(r, client.activity))]
    if r.random() < COMPROMISED_DAY_PROB:
        items += [_normal_tx(r, client, acc, day_start, 0, prefix, True) for _ in range(r.randint(2, 5))]
    items.sort(key=lambda t: t.timestamp)
    return tuple(Tx(**{**t.__dict__, "transaction_id": f"{prefix}-{n:02d}"}) for n, t in enumerate(items))


def msk_day(t: datetime) -> date:
    return (t + MSK).date()


def history_bounds(now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=HISTORY_DAYS), now


def account_transactions(acc_idx: int, start: datetime, end: datetime) -> list[Tx]:
    out = []
    d = msk_day(start)
    while d <= msk_day(end):
        out += [t for t in account_day(acc_idx, d) if start <= t.timestamp < end]
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- «живые» транзакции

def live_minute(minute: int) -> tuple[Tx, ...]:
    """Пачка новых операций за минуту (epoch minute). Метки видны только через LABEL_DELAY."""
    return _live_minute(minute)


@lru_cache(maxsize=4096)
def _live_minute(minute: int) -> tuple[Tx, ...]:
    clients, accounts = clients_and_accounts()
    r = rng_for("live", minute)
    base = datetime.fromtimestamp(minute * 60, tz=timezone.utc)
    items: list[Tx] = []
    while len(items) < LIVE_PER_MINUTE:
        acc = accounts[r.randrange(len(accounts))]
        client = clients[acc.client_idx]
        fraud = r.random() < LIVE_FRAUD_ACCOUNT_PROB
        for _ in range(r.randint(2, 4) if fraud else 1):
            t = _normal_tx(r, client, acc, base, 0, "x", fraud)
            items.append(Tx(**{**t.__dict__, "timestamp": base + timedelta(seconds=r.randint(0, 59))}))
    items = items[:LIVE_PER_MINUTE]
    items.sort(key=lambda t: t.timestamp)
    return tuple(Tx(**{**t.__dict__, "transaction_id": f"tx-live-{minute}-{n:02d}"}) for n, t in enumerate(items))
