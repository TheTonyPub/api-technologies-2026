"""Эталонные ответы для проверки сценария на защите (и позже — для CI).

Данные моков детерминированы, поэтому по дате и времени можно заранее посчитать, что должна показать
система команды. Скрипт считает это той же формулой, что и моки, и теми же моделями .dill.

    python -m tools.expected capacity --date 2026-11-19
    python -m tools.expected antifraud --from 2026-11-19T09:00:00Z --minutes 60
    python -m tools.expected spark --at 2026-11-19T09:00:00Z --since 2026-11-12T00:00:00Z

Нужны requirements.txt и requirements-models.txt, модели — в models/artifacts (или --models DIR).
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dill
import numpy as np
import pandas as pd

from mocks.common import bank, companies as co
from mocks.monitoring import metrics as mx

warnings.filterwarnings("ignore")


def ts(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def load(models: Path, name: str) -> dict:
    with open(models / f"{name}.dill", "rb") as f:
        return dill.load(f)


# ---------------------------------------------------------------- прогноз мощности

def daily_means(s: mx.Server, first_day: int, n_days: int) -> dict[str, np.ndarray]:
    minutes = np.arange(first_day * 1440, (first_day + n_days) * 1440, dtype=np.int64)
    v = mx.compute(s, minutes)
    pres = v["present"].reshape(n_days, 24, 60)
    out = {}
    for name in ("cpu", "ram", "disk"):
        arr = np.where(pres, v[name].reshape(n_days, 24, 60), np.nan)
        with np.errstate(all="ignore"):
            out[name] = np.nanmean(np.nanmean(arr, axis=2), axis=1)
    return out


def capacity(args) -> dict:
    art = load(args.models, "capacity-forecast-v1")
    feats = art["meta"]["features"]
    day = (date.fromisoformat(args.date) - date(1970, 1, 1)).days
    alerts, offline = [], []
    for s in mx.servers():
        if mx.status(s, day * 1440) == "offline":
            offline.append(s.server_id)
        means = daily_means(s, day - 30, 30)
        for metric in ("cpu", "ram", "disk"):
            lags = means[metric]
            if np.isnan(lags).any():
                continue
            row = pd.DataFrame([[metric, *lags]], columns=feats)
            for h in args.horizons:
                peak = float(art["models"][h]["peak"].predict(row)[0])
                if peak >= args.threshold:
                    alerts.append({"serverId": s.server_id, "metric": metric, "horizon": h, "peak": round(peak, 1)})
    return {"date": args.date, "threshold": args.threshold, "horizons": args.horizons,
            "servers_total": len(mx.servers()), "offline": offline,
            "alert_servers": sorted({a["serverId"] for a in alerts}), "alerts": alerts}


# ---------------------------------------------------------------- антифрод

def antifraud(args) -> dict:
    art = load(args.models, "antifraud-v1")
    meta = art["meta"]
    start = ts(args.start)
    _, accounts = bank.clients_and_accounts()
    idx = {a.account_id: i for i, a in enumerate(accounts)}
    m0 = int(start.timestamp()) // 60
    live = [t for m in range(m0, m0 + args.minutes) for t in bank.live_minute(m)]
    hist: dict[int, list[tuple[datetime, float]]] = {}
    rows, y = [], []
    for t in live:
        ai = idx[t.account_id]
        if ai not in hist:
            hist[ai] = [(h.timestamp, h.amount)
                        for h in bank.account_transactions(ai, start - timedelta(days=30), start)]
        h30 = [h for h in hist[ai] if h[0] < t.timestamp and t.timestamp - h[0] <= timedelta(days=30)]
        m = bank.merchant_by_id(t.merchant_id) if t.merchant_id else None
        rows.append({"amount": t.amount,
                     "avg_amount_30d": sum(h[1] for h in h30) / len(h30) if h30 else t.amount,
                     "tx_count_24h": sum(1 for h in h30 if t.timestamp - h[0] <= timedelta(hours=24)),
                     "geo_risk": bank.region_risk(t.region_code), "merchant_risk": m.risk if m else 0.0,
                     "hour": t.timestamp.hour})
        y.append(int(t.is_fraud))
        hist[ai].append((t.timestamp, t.amount))
    p = art["model"].predict_proba(pd.DataFrame(rows, columns=meta["features"]))[:, 1]
    pred = (p >= meta["threshold"]).astype(int)
    tp = int(((pred == 1) & (np.array(y) == 1)).sum())
    fp = int(((pred == 1) & (np.array(y) == 0)).sum())
    fn = int(((pred == 0) & (np.array(y) == 1)).sum())
    month_tx = sum(len(bank.account_transactions(i, start - timedelta(days=30), start)) for i in range(len(accounts)))
    return {"from": start.isoformat(), "minutes": args.minutes, "live_transactions": len(live),
            "fraud": sum(y), "flagged": int(pred.sum()), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "clients": bank.N_CLIENTS, "accounts": len(accounts), "transactions_30d_before": month_tx}


# ---------------------------------------------------------------- СПАРК

def spark(args) -> dict:
    at = ts(args.at)
    comps, groups, _ = co.universe()
    states = [co.company_at(c.idx, at) for c in comps]
    flags = co.bank_client_flags()
    out = {"at": at.isoformat(), "companies": len(states),
           "groups_with_members": len({s.group_id for s in states if s.group_id}),
           "bank_clients": sum(1 for i in flags if flags[i]),
           "status": dict(Counter(s.status for s in states))}
    if args.since:
        since = ts(args.since)
        ch = co.changes_between(since, at)
        per = Counter(c.idx for c in ch)
        out["changes_since"] = {"since": since.isoformat(), "changes": len(ch),
                                "companies_changed": len(per), "by_kind": dict(Counter(c.kind for c in ch))}
        # компании для показа SCD2: больше всего изменений, среди них адрес или группа
        demo = [i for i, _ in per.most_common() if any(c.idx == i and c.kind in ("address", "group") for c in ch)][:3]
        out["scd2_demo"] = [{"inn": comps[i].inn, "versions_since": per[i] + 1,
                             "changes": [{"ts": c.ts.isoformat(), "kind": c.kind} for c in ch if c.idx == i]}
                            for i in demo]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, default=Path(__file__).resolve().parents[1] / "models" / "artifacts")
    sub = ap.add_subparsers(dest="case", required=True)
    c = sub.add_parser("capacity")
    c.add_argument("--date", default=date.today().isoformat(), help="день расчёта прогноза (UTC)")
    c.add_argument("--threshold", type=float, default=80.0)
    c.add_argument("--horizons", nargs="+", default=["1d", "1m"])
    a = sub.add_parser("antifraud")
    a.add_argument("--from", dest="start", required=True, help="начало прогона потока live, UTC")
    a.add_argument("--minutes", type=int, default=60)
    s = sub.add_parser("spark")
    s.add_argument("--at", default=datetime.now(timezone.utc).isoformat())
    s.add_argument("--since", help="с какого момента считать изменения (инкремент GetChangedCompanies)")
    args = ap.parse_args()
    res = {"capacity": capacity, "antifraud": antifraud, "spark": spark}[args.case](args)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
