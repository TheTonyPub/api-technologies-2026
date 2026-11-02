"""Серверы ИС и их метрики. Значение за любую минуту — формула от (сервер, минута), ничего не хранится."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from ..common.core import SEED, rng_for, stable_int

T0 = datetime(2025, 11, 1, tzinfo=timezone.utc)  # точка отсчёта трендов
T0_MIN = int(T0.timestamp()) // 60

INFORMATION_SYSTEMS = [
    ("is-01", "Финансы (ERP)", "Финансовый департамент", "high", "business"),
    ("is-02", "CRM продаж", "Коммерческий департамент", "high", "business"),
    ("is-03", "Интернет-магазин", "Электронная коммерция", "critical", "consumer"),
    ("is-04", "Кадры и зарплата", "HR", "medium", "business"),
    ("is-05", "Складской учёт", "Логистика", "high", "business"),
    ("is-06", "Биллинг", "ИТ-департамент", "critical", "consumer"),
    ("is-07", "Электронный документооборот", "Административный департамент", "medium", "business"),
    ("is-08", "Аналитическое хранилище (DWH)", "Отдел аналитики", "medium", "batch"),
]
ROLES = ["app", "app", "db", "cache", "worker"]


@dataclass(frozen=True)
class Server:
    idx: int
    server_id: str
    hostname: str
    is_id: str
    role: str
    cpu_cores: int
    ram_gb: int
    disk_gb: int
    profile: str
    cpu_base: float
    cpu_amp: float
    cpu_trend: float  # п.п. в день
    cpu_noise: float
    weekend: float
    ram_base: float
    ram_amp: float
    ram_trend: float
    disk_start: float  # % на T0
    disk_growth: float  # п.п. в день
    offline_since_min: int | None
    seed: int


DISK_CROSS = {3: "2026-11-28", 17: "2026-12-10", 29: "2026-12-22"}  # диск перейдёт 80%
CPU_CROSS = {8: "2026-12-05", 22: "2026-12-15", 36: "2026-12-28"}   # дневной пик CPU перейдёт 80%
OFFLINE = {12: "2026-10-20T09:15:00", 33: "2026-10-27T22:40:00"}


def _min(iso_str: str) -> int:
    t = datetime.fromisoformat(iso_str)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return int(t.timestamp()) // 60


@lru_cache(maxsize=1)
def servers() -> list[Server]:
    out = []
    for i in range(40):
        is_id, is_name, _, _, profile = INFORMATION_SYSTEMS[i // 5]
        r = rng_for("server", i)
        role = ROLES[i % 5]
        short = is_id.replace("is-", "is")
        cpu_base = r.uniform(12, 35)
        cpu_amp = r.uniform(8, 25)
        cpu_trend = r.uniform(-0.005, 0.015)
        disk_start = r.uniform(20, 55)
        disk_growth = r.uniform(0.005, 0.05)
        if i in DISK_CROSS:
            days = (_min(DISK_CROSS[i]) - T0_MIN) / 1440
            disk_growth = (80 - disk_start) / days
        if i in CPU_CROSS:
            days = (_min(CPU_CROSS[i]) - T0_MIN) / 1440
            cpu_trend = (80 - (cpu_base + cpu_amp)) / days
        out.append(Server(
            idx=i, server_id=f"srv-{i + 1:03d}", hostname=f"{short}-{role}-{i % 5 + 1:02d}.prod.example.local",
            is_id=is_id, role=role, cpu_cores=r.choice([4, 8, 16, 32]), ram_gb=r.choice([16, 32, 64, 128]),
            disk_gb=r.choice([200, 500, 1000, 2000]), profile=profile, cpu_base=cpu_base, cpu_amp=cpu_amp,
            cpu_trend=cpu_trend, cpu_noise=r.uniform(1.5, 4), weekend=r.uniform(0.45, 0.8),
            ram_base=r.uniform(30, 55), ram_amp=r.uniform(3, 10), ram_trend=r.uniform(-0.003, 0.02),
            disk_start=disk_start, disk_growth=disk_growth,
            offline_since_min=_min(OFFLINE[i]) if i in OFFLINE else None,
            seed=stable_int(SEED, "server-noise", i) & 0xFFFFFFFF,
        ))
    return out


def server_by_id(sid: str) -> Server | None:
    if not (sid.startswith("srv-") and sid[4:].isdigit()):
        return None
    i = int(sid[4:]) - 1
    s = servers()
    return s[i] if 0 <= i < len(s) else None


# ---------------------------------------------------------------- генерация

def _u(x: np.ndarray, salt: int) -> np.ndarray:
    """splitmix64 -> равномерное [0, 1) для каждого элемента."""
    with np.errstate(over="ignore"):
        z = x.astype(np.uint64) + np.uint64((salt * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _gauss(x: np.ndarray, salt: int) -> np.ndarray:
    u1 = np.maximum(_u(x, salt), 1e-12)
    u2 = _u(x, salt + 1)
    return np.sqrt(-2 * np.log(u1)) * np.cos(2 * np.pi * u2)


def _profile(hour: np.ndarray, kind: str) -> np.ndarray:
    if kind == "business":
        return np.clip(np.sin(np.pi * (hour - 8) / 11), 0, None)  # 8:00–19:00
    if kind == "consumer":
        return 0.35 + 0.65 * np.clip(np.sin(np.pi * (hour - 10) / 14), 0, None)  # пик к 17–21
    return np.where((hour >= 1) & (hour < 5), 1.0, 0.15)  # ночные пакеты


def compute(s: Server, minutes: np.ndarray) -> dict[str, np.ndarray]:
    """cpu, ram, disk (%) и маска наличия данных для массива epoch-минут."""
    m = minutes.astype(np.int64)
    local = m + 180
    hour = (local % 1440) / 60.0
    day = local // 1440
    weekday = (day + 3) % 7
    weekend = weekday >= 5
    days = (m - T0_MIN) / 1440.0
    prof = _profile(hour, s.profile)
    wk = np.where(weekend, 1.2 if s.profile == "consumer" else s.weekend, 1.0)
    x = m ^ np.int64(s.seed)
    hour_key = (m // 60) ^ np.int64(s.seed)
    spike = np.where(_u(hour_key, 7) < 0.01, 20 + 20 * _u(hour_key, 8), 0.0)
    cpu = s.cpu_base + s.cpu_trend * days + s.cpu_amp * prof * wk + s.cpu_noise * _gauss(x, 1) + spike
    ram = s.ram_base + s.ram_trend * days + s.ram_amp * prof + 1.2 * _gauss(x, 3) + 0.3 * spike
    disk = s.disk_start + s.disk_growth * days + 0.05 * _gauss(x, 5)
    present = _u(x, 9) >= 0.005
    if s.offline_since_min is not None:
        present &= m < s.offline_since_min
    return {"cpu": np.clip(cpu, 0.5, 99.9), "ram": np.clip(ram, 1, 99.9), "disk": np.clip(disk, 1, 99.9),
            "present": present}


def status(s: Server, now_min: int) -> str:
    return "offline" if s.offline_since_min is not None and now_min >= s.offline_since_min else "online"
