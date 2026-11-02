"""Вселенная юрлиц: общая для /spark (источник) и /abs (кто из них клиент банка).

Компании, группы и журнал изменений строятся детерминированно из SEED.
Состояние компании на момент t = базовая карточка + все изменения с ts <= t.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from . import reference as ref
from .core import rng_for

N_COMPANIES = 1000
N_GROUPED = 600
CHANGES_FROM = datetime(2026, 9, 1, tzinfo=timezone.utc)
CHANGES_TO = datetime(2027, 8, 31, tzinfo=timezone.utc)
DAILY_CHANGE_PROB = 0.03

INN_W = [2, 4, 10, 3, 5, 9, 4, 6, 8]


def inn_check(d9: str) -> str:
    return str(sum(int(c) * w for c, w in zip(d9, INN_W)) % 11 % 10)


def ogrn_check(d12: str) -> str:
    return str(int(d12) % 11 % 10)


def is_valid_inn(inn: str) -> bool:
    return len(inn) == 10 and inn.isdigit() and inn_check(inn[:9]) == inn[9]


@dataclass(frozen=True)
class Company:
    idx: int
    inn: str
    ogrn: str
    kpp: str
    short_name: str
    full_name: str
    status: str  # ACTIVE | LIQUIDATING | LIQUIDATED
    registration_date: date
    region_code: str
    legal_address: str
    okved: str
    authorized_capital: int
    employees: int
    head_name: str
    head_position: str
    group_id: str | None
    revision: int = 1
    actual_date: datetime | None = None


@dataclass
class Group:
    group_id: str
    name: str
    parent_idx: int
    # idx -> (role, sharePercent) для базового состава; при переходе в группу роль affiliate
    roles: dict[int, tuple[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    ts: datetime
    idx: int
    kind: str  # address | head | kpp | okved | status | group
    payload: tuple


def _person_name(r) -> str:
    if r.random() < 0.6:
        return f"{r.choice(ref.SURNAMES)} {r.choice(ref.MALE_FIRST)} {r.choice(ref.MALE_PATRONYMIC)}"
    return f"{ref.female_surname(r.choice(ref.SURNAMES))} {r.choice(ref.FEMALE_FIRST)} {r.choice(ref.FEMALE_PATRONYMIC)}"


def _address(r, region_code: str) -> str:
    region, city = ref.REGIONS[region_code]
    zip_code = f"{r.randint(100000, 699999)}"
    prefix = "" if region.startswith("г.") else f"{region}, г. {city}, "
    if region.startswith("г."):
        prefix = f"{region}, "
    return f"{zip_code}, {prefix}{r.choice(ref.STREETS)}, д. {r.randint(1, 180)}, оф. {r.randint(1, 450)}"


@lru_cache(maxsize=1)
def universe() -> tuple[list[Company], dict[str, Group], dict[str, int]]:
    companies: list[Company] = []
    used_inn: set[str] = set()
    for i in range(N_COMPANIES):
        r = rng_for("company", i)
        region = r.choices(ref.REGION_CODES, weights=ref.REGION_WEIGHTS)[0]
        while True:
            d9 = f"{region}{r.randint(1, 99):02d}{r.randint(0, 99999):05d}"
            inn = d9 + inn_check(d9)
            if inn not in used_inn:
                used_inn.add(inn)
                break
        reg = date(1995, 1, 1) + timedelta(days=r.randint(0, (date(2025, 12, 31) - date(1995, 1, 1)).days))
        d12 = f"1{reg.year % 100:02d}{region}{r.randint(0, 9999999):07d}"
        word = f"{r.choice(ref.NAME_WORDS_A)} {r.choice(ref.NAME_WORDS_B)}"
        form_short, form_full = ("ООО", "Общество с ограниченной ответственностью") if r.random() < 0.85 else \
            ("АО", "Акционерное общество")
        status = "ACTIVE"
        x = r.random()
        if x < 0.03:
            status = "LIQUIDATED"
        elif x < 0.06:
            status = "LIQUIDATING"
        companies.append(Company(
            idx=i, inn=inn, ogrn=d12 + ogrn_check(d12), kpp=f"{inn[:4]}01001",
            short_name=f"{form_short} «{word}»", full_name=f"{form_full} «{word}»",
            status=status, registration_date=reg, region_code=region,
            legal_address=_address(r, region), okved=r.choice(ref.OKVED_CODES),
            authorized_capital=int(round(10 ** r.uniform(4, 8), -3)),
            employees=max(1, int(10 ** r.uniform(0, 3.5))),
            head_name=_person_name(r), head_position=r.choice(ref.HEAD_POSITIONS), group_id=None,
        ))

    # группы: первые N_GROUPED компаний (в случайном порядке) раскладываются по группам 2..15
    r = rng_for("groups")
    order = list(range(N_COMPANIES))
    r.shuffle(order)
    groups: dict[str, Group] = {}
    pos, g = 0, 0
    while pos < N_GROUPED:
        size = min(r.randint(2, 15), N_GROUPED - pos)
        if size < 2:
            break
        g += 1
        gid = f"grp-{g:06d}"
        members = order[pos:pos + size]
        pos += size
        parent = members[0]
        base_word = companies[parent].short_name.split("«")[1].rstrip("»")
        grp = Group(group_id=gid, name=f"Группа «{base_word}»", parent_idx=parent)
        grp.roles[parent] = ("parent", 100.0)
        for m in members[1:]:
            grp.roles[m] = ("subsidiary", round(r.uniform(51, 100), 1)) if r.random() < 0.7 else \
                ("affiliate", round(r.uniform(20, 50), 1))
        groups[gid] = grp
        for m in members:
            companies[m] = replace(companies[m], group_id=gid)
    by_inn = {c.inn: c.idx for c in companies}
    return companies, groups, by_inn


@lru_cache(maxsize=1)
def change_log() -> dict[int, list[Change]]:
    companies, groups, _ = universe()
    group_ids = sorted(groups)
    log: dict[int, list[Change]] = {c.idx: [] for c in companies}
    days = (CHANGES_TO - CHANGES_FROM).days
    for c in companies:
        r = rng_for("changes", c.idx)
        status = c.status
        group = c.group_id
        for d in range(days):
            if r.random() >= DAILY_CHANGE_PROB:
                continue
            ts = CHANGES_FROM + timedelta(days=d, seconds=r.randint(0, 86399))
            kind = r.choices(["address", "head", "kpp", "okved", "status", "group"],
                             weights=[30, 30, 10, 10, 10, 10])[0]
            if status == "LIQUIDATED":
                continue  # ликвидированная компания больше не меняется
            if kind == "status":
                status = "LIQUIDATING" if status == "ACTIVE" else "LIQUIDATED"
                payload = (status,)
            elif kind == "group":
                is_parent = group is not None and groups[group].parent_idx == c.idx
                if is_parent:
                    kind, payload = "head", (_person_name(r), r.choice(ref.HEAD_POSITIONS))
                else:
                    group = None if (group and r.random() < 0.3) else r.choice(group_ids)
                    payload = (group,)
            elif kind == "address":
                payload = (_address(r, c.region_code),)
            elif kind == "head":
                payload = (_person_name(r), r.choice(ref.HEAD_POSITIONS))
            elif kind == "kpp":
                payload = (f"{c.inn[:4]}{r.randint(1, 99):02d}001",)
            else:
                payload = (r.choice(ref.OKVED_CODES),)
            log[c.idx].append(Change(ts=ts, idx=c.idx, kind=kind, payload=payload))
    return log


@lru_cache(maxsize=1)
def _all_changes_sorted() -> list[Change]:
    out = [ch for chs in change_log().values() for ch in chs]
    out.sort(key=lambda ch: (ch.ts, ch.idx))
    return out


def changes_between(since: datetime, until: datetime) -> list[Change]:
    allc = _all_changes_sorted()
    ts_list = [c.ts for c in allc]
    lo = bisect.bisect_right(ts_list, since)
    hi = bisect.bisect_right(ts_list, until)
    return allc[lo:hi]


@lru_cache(maxsize=20000)
def _state(idx: int, n_applied: int) -> Company:
    companies, _, _ = universe()
    c = companies[idx]
    for ch in change_log()[idx][:n_applied]:
        if ch.kind == "address":
            c = replace(c, legal_address=ch.payload[0])
        elif ch.kind == "head":
            c = replace(c, head_name=ch.payload[0], head_position=ch.payload[1])
        elif ch.kind == "kpp":
            c = replace(c, kpp=ch.payload[0])
        elif ch.kind == "okved":
            c = replace(c, okved=ch.payload[0])
        elif ch.kind == "status":
            c = replace(c, status=ch.payload[0])
        elif ch.kind == "group":
            c = replace(c, group_id=ch.payload[0])
        c = replace(c, revision=c.revision + 1, actual_date=ch.ts)
    return c


def company_at(idx: int, t: datetime) -> Company:
    chs = change_log()[idx]
    n = bisect.bisect_right([ch.ts for ch in chs], t)
    c = _state(idx, n)
    if c.actual_date is None:
        c = replace(c, actual_date=datetime(c.registration_date.year, c.registration_date.month,
                                            c.registration_date.day, tzinfo=timezone.utc))
    return c


def group_members_at(group_id: str, t: datetime) -> list[tuple[Company, str, float]]:
    companies, groups, _ = universe()
    grp = groups[group_id]
    out = []
    for c in companies:
        st = company_at(c.idx, t)
        if st.group_id == group_id:
            role, share = grp.roles.get(c.idx, ("affiliate", 25.0))
            out.append((st, role, share))
    out.sort(key=lambda x: (x[1] != "parent", x[0].inn))
    return out


# ---------------------------------------------------------------- клиенты банка (для /abs и модели скоринга)

OKVED_AFFINITY = {"62.01": 0.6, "62.02": 0.5, "46.90": 0.3, "47.11": 0.1, "41.20": 0.2, "49.41": 0.0,
                  "10.11": -0.2, "68.20": 0.4, "70.22": 0.3, "25.11": -0.1, "56.10": -0.4, "86.10": -0.3,
                  "01.11": -0.6, "35.11": 0.2, "73.11": 0.1}


@lru_cache(maxsize=1)
def bank_client_flags() -> dict[int, bool]:
    """Кто из компаний клиент банка. Зависит от признаков, которые потом видит модель скоринга."""
    companies, groups, _ = universe()
    affinity = {gid: rng_for("group-affinity", gid).gauss(0, 1.2) for gid in groups}
    sizes = {gid: len(g.roles) for gid, g in groups.items()}
    ref_day = date(2026, 9, 1)
    flags = {}
    for c in companies:
        r = rng_for("bank-client", c.idx)
        age_years = (ref_day - c.registration_date).days / 365.25
        logit = -1.6 + 0.45 * math.log1p(age_years) + OKVED_AFFINITY[c.okved]
        if c.group_id:
            logit += affinity[c.group_id] + 0.06 * min(sizes[c.group_id], 12)
        if c.status != "ACTIVE":
            logit -= 2.0
        logit += r.gauss(0, 0.5)
        flags[c.idx] = r.random() < 1 / (1 + math.exp(-logit))
    return flags
