"""Мок мониторинга серверов ИС. Путь на сервере: /monitoring."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
from fastapi import Depends, Path, Query, Request
from pydantic import BaseModel, Field

from ..common.core import ApiError, RateLimiter, create_app, require_team
from . import metrics as mx

DESCRIPTION = """Серверы информационных систем вымышленной компании и их метрики CPU, RAM и диска.

**Кому нужен.** Кейс «Прогноз мощности серверов». В архитектуре команды агенты мониторинга сами
отправляют метрики в Metrics Collector (`POST /v1/metrics`). Этот мок изображает сами серверы,
а **агента команда пишет сама**: процесс, который раз в минуту читает
`/servers/{serverId}/metrics/current` по всем серверам и отправляет замеры в свой Collector.
История за год нужна для первичной заливки Data Store и для прогнозов на 1 / 6 / 12 месяцев.

Особенности данных: суточный и недельный цикл, тренды, редкие часовые пики CPU, около 0,5% минут
без данных (агент не ответил), два сервера сейчас offline. У шести серверов нагрузка в декабре 2026
перейдёт 80%: на них должен сработать Alert Worker."""

app = create_app(
    "Мок мониторинга серверов ИС", DESCRIPTION,
    tags=[{"name": "inventory", "description": "ИС и серверы. Кейс: Прогноз мощности (справочник серверов/ИС)."},
          {"name": "metrics", "description": "Метрики. Кейс: Прогноз мощности (агент, история, обучение не нужно)."}],
)
limiter = RateLimiter(int(os.getenv("MONITORING_RPS", "50")))
STEPS = {"1m": 1, "5m": 5, "1h": 60, "1d": 1440}
MAX_POINTS = 10_000
HISTORY_DAYS = 366


def team(request: Request, t: str = Depends(require_team)) -> str:
    limiter.check(t)
    return t


def now_min() -> int:
    return int(datetime.now(timezone.utc).timestamp()) // 60


def ts(minute: int) -> datetime:
    return datetime.fromtimestamp(minute * 60, tz=timezone.utc)


class InformationSystemOut(BaseModel):
    isId: str = Field(examples=["is-01"])
    name: str
    owner: str
    criticality: Literal["medium", "high", "critical"]
    serverIds: list[str]


class ServerOut(BaseModel):
    serverId: str = Field(examples=["srv-001"])
    hostname: str
    isId: str
    role: Literal["app", "db", "cache", "worker"]
    cpuCores: int
    ramGb: int
    diskGb: int
    status: Literal["online", "offline"]


class Sample(BaseModel):
    serverId: str
    measuredAt: datetime = Field(description="Начало минуты замера, UTC")
    cpuPercent: float
    ramPercent: float
    diskPercent: float


class Point(BaseModel):
    ts: datetime = Field(description="Начало интервала, UTC")
    cpuPercent: float
    ramPercent: float
    diskPercent: float
    samples: int = Field(description="Сколько минутных замеров попало в интервал")


class History(BaseModel):
    serverId: str
    step: Literal["1m", "5m", "1h", "1d"]
    agg: Literal["mean", "max"]
    points: list[Point]


def server_out(s: mx.Server) -> dict:
    return {"serverId": s.server_id, "hostname": s.hostname, "isId": s.is_id, "role": s.role,
            "cpuCores": s.cpu_cores, "ramGb": s.ram_gb, "diskGb": s.disk_gb, "status": mx.status(s, now_min())}


def get_server(server_id: str) -> mx.Server:
    s = mx.server_by_id(server_id)
    if not s:
        raise ApiError(404, "SERVER_NOT_FOUND", f"Сервер {server_id} не найден")
    return s


@app.get("/v1/information-systems", tags=["inventory"], response_model=list[InformationSystemOut],
         summary="Информационные системы",
         description="Кейс Прогноз мощности: справочник ИС для привязки серверов (`/information-systems` в API команды).")
def list_is(t: str = Depends(team)):
    srv = mx.servers()
    return [{"isId": i, "name": n, "owner": o, "criticality": c,
             "serverIds": [s.server_id for s in srv if s.is_id == i]} for i, n, o, c, _ in mx.INFORMATION_SYSTEMS]


@app.get("/v1/servers", tags=["inventory"], response_model=list[ServerOut],
         summary="Серверы", description="Кейс Прогноз мощности: список серверов, по которым агент собирает метрики.")
def list_servers(t: str = Depends(team), isId: str | None = None):
    return [server_out(s) for s in mx.servers() if isId is None or s.is_id == isId]


@app.get("/v1/servers/{serverId}", tags=["inventory"], response_model=ServerOut, summary="Сервер")
def one_server(serverId: str = Path(examples=["srv-001"]), t: str = Depends(team)):
    return server_out(get_server(serverId))


@app.get("/v1/servers/{serverId}/metrics/current", tags=["metrics"], response_model=Sample,
         summary="Замер за текущую минуту",
         description="Кейс Прогноз мощности: это читает агент раз в минуту и пересылает в Metrics Collector. "
                     "Если за минуту данных нет — 503 `NO_DATA` (повторите в следующую минуту), "
                     "если сервер выключен — 503 `SERVER_OFFLINE`.")
def current(serverId: str = Path(examples=["srv-001"]), t: str = Depends(team)):
    s = get_server(serverId)
    m = now_min()
    if mx.status(s, m) == "offline":
        raise ApiError(503, "SERVER_OFFLINE", f"Сервер {serverId} не на связи с {ts(s.offline_since_min):%Y-%m-%d %H:%M} UTC")
    v = mx.compute(s, np.array([m]))
    if not v["present"][0]:
        raise ApiError(503, "NO_DATA", "Агент на сервере не прислал замер за эту минуту",
                       headers={"Retry-After": "60"})
    return {"serverId": s.server_id, "measuredAt": ts(m), "cpuPercent": round(float(v["cpu"][0]), 2),
            "ramPercent": round(float(v["ram"][0]), 2), "diskPercent": round(float(v["disk"][0]), 2)}


@app.get("/v1/servers/{serverId}/metrics", tags=["metrics"], response_model=History,
         summary="История метрик",
         description="Кейс Прогноз мощности: первичная заливка истории (до 366 дней назад) и данные для прогнозов. "
                     "Не больше 10 000 точек за запрос: `1m` — около 7 суток, `1h` — больше года. "
                     "Интервалы без единого замера пропускаются.")
def history(serverId: str = Path(examples=["srv-001"]), t: str = Depends(team),
            from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
            step: Literal["1m", "5m", "1h", "1d"] = "1h", agg: Literal["mean", "max"] = "mean"):
    s = get_server(serverId)
    nm = now_min()
    end = min(int((to or ts(nm)).timestamp()) // 60, nm + 1)
    start = int((from_ or ts(end) - timedelta(days=1)).timestamp()) // 60
    start = max(start, nm - HISTORY_DAYS * 1440)
    k = STEPS[step]
    start -= start % k
    if start >= end:
        raise ApiError(400, "INVALID_REQUEST", "from должен быть раньше to и не в будущем")
    n_points = -(-(end - start) // k)
    if n_points > MAX_POINTS:
        raise ApiError(400, "INVALID_REQUEST", f"Слишком много точек ({n_points}): увеличьте step или сузьте интервал")
    minutes = np.arange(start, start + n_points * k, dtype=np.int64)
    v = mx.compute(s, minutes)
    present = v["present"] & (minutes < end)
    points = []
    pres = present.reshape(n_points, k)
    cnt = pres.sum(axis=1)
    out = {}
    for name in ("cpu", "ram", "disk"):
        arr = np.where(pres, v[name].reshape(n_points, k), np.nan)
        with np.errstate(all="ignore"):
            out[name] = np.nanmean(arr, axis=1) if agg == "mean" else np.nanmax(arr, axis=1)
    for i in range(n_points):
        if cnt[i] == 0:
            continue
        points.append({"ts": ts(start + i * k), "cpuPercent": round(float(out["cpu"][i]), 2),
                       "ramPercent": round(float(out["ram"][i]), 2), "diskPercent": round(float(out["disk"][i]), 2),
                       "samples": int(cnt[i])})
    return {"serverId": s.server_id, "step": step, "agg": agg, "points": points}
