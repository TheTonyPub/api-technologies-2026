"""Обучение трёх готовых моделей для команд на данных моков.

Запуск из папки external-services:  python -m models.train_models
Результат: models/artifacts/{antifraud,company-scoring,capacity-forecast}-v1.dill

Каждый артефакт — словарь из обычных объектов scikit-learn и метаданных, без собственного кода.
Поэтому для загрузки нужны только dill, pandas и scikit-learn той же версии (см. meta["requirements"]).
"""

from __future__ import annotations

import platform
import warnings
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dill
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, f1_score, mean_absolute_error, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from mocks.common import bank, companies
from mocks.monitoring import metrics as mx

OUT = Path(__file__).parent / "artifacts"
TRAINED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
REQ = {"python": ">=3.10", "scikit-learn": sklearn.__version__, "dill": dill.__version__,
       "pandas": pd.__version__, "numpy": np.__version__}


def save(name: str, artifact: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.dill"
    with open(path, "wb") as f:
        dill.dump(artifact, f)
    print(f"saved {path} ({path.stat().st_size / 1024:.0f} KB)")


# ================================================================ антифрод

AF_FEATURES = ["amount", "avg_amount_30d", "tx_count_24h", "geo_risk", "merchant_risk", "hour"]


def antifraud_rows(acc_ids, start: date, days: int) -> pd.DataFrame:
    """Признаки считаются по истории счёта ровно так, как это должна делать команда."""
    rows = []
    for a in acc_ids:
        hist: deque = deque()  # (ts, amount) за последние 30 дней
        for d in range(days):
            for t in bank.account_day(a, start + timedelta(days=d)):
                while hist and t.timestamp - hist[0][0] > timedelta(days=30):
                    hist.popleft()
                avg30 = sum(x[1] for x in hist) / len(hist) if hist else t.amount
                cnt24 = sum(1 for x in hist if t.timestamp - x[0] <= timedelta(hours=24))
                m = bank.merchant_by_id(t.merchant_id) if t.merchant_id else None
                rows.append({"amount": t.amount, "avg_amount_30d": round(avg30, 2), "tx_count_24h": cnt24,
                             "geo_risk": bank.region_risk(t.region_code), "merchant_risk": m.risk if m else 0.0,
                             "hour": t.timestamp.hour, "is_fraud": int(t.is_fraud),
                             "day": d})
                hist.append((t.timestamp, t.amount))
    return pd.DataFrame(rows)


def train_antifraud():
    rng = np.random.default_rng(1)
    acc_ids = rng.choice(len(bank.clients_and_accounts()[1]), size=1200, replace=False)
    df = antifraud_rows(acc_ids, date(2025, 11, 1), 330)
    df = df[df.day >= 30]  # первые 30 дней — только разогрев истории
    train, test = df[df.day < 270], df[df.day >= 270]
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
                                         l2_regularization=1.0, random_state=7)
    clf.fit(train[AF_FEATURES], train.is_fraud)
    p = clf.predict_proba(test[AF_FEATURES])[:, 1]
    best = max(np.arange(0.1, 0.95, 0.05), key=lambda th: f1_score(test.is_fraud, p >= th))
    pred = p >= best
    m = {"rows_train": int(len(train)), "rows_test": int(len(test)), "fraud_rate": round(float(df.is_fraud.mean()), 4),
         "roc_auc": round(float(roc_auc_score(test.is_fraud, p)), 4), "pr_auc": round(float(average_precision_score(test.is_fraud, p)), 4),
         "precision": round(float(precision_score(test.is_fraud, pred)), 4), "recall": round(float(recall_score(test.is_fraud, pred)), 4),
         "f1": round(float(f1_score(test.is_fraud, pred)), 4)}
    print("antifraud", m, "threshold", round(float(best), 2))
    save("antifraud-v1", {
        "model": clf,
        "meta": {
            "name": "antifraud", "version": "1.0.0", "case": "Антифрод", "trained_at": TRAINED_AT,
            "task": "Вероятность того, что операция мошенническая (score 0..1)",
            "features": AF_FEATURES,
            "feature_doc": {
                "amount": "сумма операции в валюте счёта (поле amount из АБС)",
                "avg_amount_30d": "средняя сумма операций этого счёта за 30 дней до операции (сама операция не входит); "
                                  "если истории нет — равна amount",
                "tx_count_24h": "число операций счёта за 24 часа до операции (сама операция не входит)",
                "geo_risk": "risk_score региона операции: GET /client-data/v1/regions/{region_code}/risk",
                "merchant_risk": "risk_score мерчанта: GET /client-data/v1/merchants/{merchant_id}/risk; "
                                 "для переводов и банкомата (merchant_id = null) — 0",
                "hour": "час операции по UTC (0..23) из timestamp",
            },
            "threshold": round(float(best), 2),
            "verdict_rule": "score >= threshold -> вердикт 1 (фрод), иначе 0",
            "metrics": m, "requirements": REQ,
            "usage": "model.predict_proba(pandas.DataFrame([features], columns=meta['features']))[:, 1]",
        },
    })


# ================================================================ скоринг юрлиц

SC_FEATURES = ["companyAgeMonths", "mainActivityCode", "status", "groupSize", "groupBankClientsCount"]


def scoring_rows(t: datetime) -> pd.DataFrame:
    cs, groups, _ = companies.universe()
    flags = companies.bank_client_flags()
    states = [companies.company_at(c.idx, t) for c in cs]
    members: dict[str, list[int]] = {}
    for s in states:
        if s.group_id:
            members.setdefault(s.group_id, []).append(s.idx)
    rows = []
    for s in states:
        grp = members.get(s.group_id, []) if s.group_id else []
        age = (t.date().year - s.registration_date.year) * 12 + (t.date().month - s.registration_date.month)
        rows.append({"companyAgeMonths": max(age, 0), "mainActivityCode": s.okved, "status": s.status,
                     "groupSize": len(grp), "groupBankClientsCount": sum(flags[i] for i in grp if i != s.idx),
                     "label": int(flags[s.idx])})
    return pd.DataFrame(rows)


def train_scoring():
    df = scoring_rows(datetime(2026, 9, 1, tzinfo=timezone.utc))
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), ["mainActivityCode", "status"]),
        ("num", StandardScaler(), ["companyAgeMonths", "groupSize", "groupBankClientsCount"]),
    ])
    pipe = Pipeline([("prep", pre), ("model", LogisticRegression(max_iter=2000, C=1.0))])
    rng = np.random.default_rng(3)
    mask = rng.random(len(df)) < 0.8
    pipe.fit(df[mask][SC_FEATURES], df[mask].label)
    p = pipe.predict_proba(df[~mask][SC_FEATURES])[:, 1]
    m = {"rows_train": int(mask.sum()), "rows_test": int((~mask).sum()), "positive_rate": round(float(df.label.mean()), 3),
         "roc_auc": round(float(roc_auc_score(df[~mask].label, p)), 4)}
    pipe.fit(df[SC_FEATURES], df.label)  # финальная модель на всех данных
    print("scoring", m)
    save("company-scoring-v1", {
        "model": pipe,
        "meta": {
            "name": "company-scoring", "version": "1.0.0", "case": "СПАРК", "trained_at": TRAINED_AT,
            "task": "Вероятность того, что юрлицо станет (является) клиентом банка, 0..1",
            "features": SC_FEATURES,
            "feature_doc": {
                "companyAgeMonths": "полных месяцев с RegistrationDate (СПАРК) до даты расчёта",
                "mainActivityCode": "код ОКВЭД (OKVED/Code из СПАРК), строка вида '62.01'",
                "status": "ACTIVE | LIQUIDATING | LIQUIDATED (Status из СПАРК)",
                "groupSize": "сколько компаний в группе, включая саму компанию (0, если группы нет)",
                "groupBankClientsCount": "сколько ДРУГИХ компаний группы — клиенты банка (/abs legal-clients)",
            },
            "metrics": m, "requirements": REQ,
            "usage": "model.predict_proba(pandas.DataFrame([features], columns=meta['features']))[:, 1]",
        },
    })


# ================================================================ прогноз мощности

HORIZONS = {"1d": 1, "1m": 30, "6m": 180, "1y": 365}
LAGS = 30
FC_FEATURES = ["metric"] + [f"d{i}" for i in range(1, LAGS + 1)]


def daily_series(s: mx.Server, first_day: int, n_days: int) -> dict[str, np.ndarray]:
    """Дневные (UTC) среднее и пик (максимум часовых средних) по каждой метрике."""
    minutes = np.arange(first_day * 1440, (first_day + n_days) * 1440, dtype=np.int64)
    v = mx.compute(s, minutes)
    pres = v["present"].reshape(n_days, 24, 60)
    out = {}
    for name in ("cpu", "ram", "disk"):
        arr = np.where(pres, v[name].reshape(n_days, 24, 60), np.nan)
        with np.errstate(all="ignore"):
            hourly = np.nanmean(arr, axis=2)
            out[f"{name}_mean"] = np.nanmean(hourly, axis=1)
            out[f"{name}_peak"] = np.nanmax(hourly, axis=1)
    return out


def train_forecast():
    first = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()) // 86400
    n_days = (date(2027, 12, 31) - date(2025, 6, 1)).days
    anchors = range(LAGS, (date(2026, 10, 31) - date(2025, 6, 1)).days, 3)
    data = {h: [] for h in HORIZONS}
    for s in mx.servers():
        ser = daily_series(s, first, n_days)
        for metric in ("cpu", "ram", "disk"):
            mean, peak = ser[f"{metric}_mean"], ser[f"{metric}_peak"]
            for a in anchors:  # a — индекс дня прогноза; d30 = день a-1
                lags = mean[a - LAGS:a]
                if np.isnan(lags).any():
                    continue
                for h, hd in HORIZONS.items():
                    tgt = a - 1 + hd
                    if tgt >= n_days or np.isnan(mean[tgt]):
                        continue
                    data[h].append([metric, *lags, mean[tgt], peak[tgt]])
    cols = FC_FEATURES + ["y_mean", "y_peak"]
    models, metrics = {}, {}
    for h, rows in data.items():
        df = pd.DataFrame(rows, columns=cols)
        rng = np.random.default_rng(5)
        mask = rng.random(len(df)) < 0.8
        models[h] = {}
        metrics[h] = {}
        for target in ("mean", "peak"):
            pipe = Pipeline([
                ("prep", ColumnTransformer([("metric", OneHotEncoder(handle_unknown="ignore"), ["metric"])],
                                           remainder="passthrough")),
                ("model", Ridge(alpha=1.0)),
            ])
            pipe.fit(df[mask][FC_FEATURES], df[mask][f"y_{target}"])
            mae = mean_absolute_error(df[~mask][f"y_{target}"], pipe.predict(df[~mask][FC_FEATURES]))
            pipe.fit(df[FC_FEATURES], df[f"y_{target}"])
            models[h][target] = pipe
            metrics[h][target] = {"mae_pp": round(float(mae), 2), "rows": int(len(df))}
    print("forecast", metrics)
    save("capacity-forecast-v1", {
        "models": models,
        "meta": {
            "name": "capacity-forecast", "version": "1.0.0", "case": "Прогноз мощности серверов",
            "trained_at": TRAINED_AT,
            "task": "Прогноз дневной загрузки (среднее и пик) CPU/RAM/диска сервера в % на горизонтах 1d, 1m, 6m, 1y",
            "horizons_days": HORIZONS,
            "features": FC_FEATURES,
            "feature_doc": {
                "metric": "cpu | ram | disk — какую метрику прогнозируем (одна строка на метрику)",
                "d1..d30": "средние значения метрики (%) за 30 последних полных суток UTC: d1 — 30 дней назад, "
                           "d30 — вчера. Суточное среднее = среднее минутных замеров за сутки",
            },
            "targets": {"mean": "среднее за сутки через горизонт (сутки D-1+h, где D — сегодня)",
                        "peak": "максимум часовых средних за те же сутки — сравнивать с порогом"},
            "metrics": metrics, "requirements": REQ,
            "usage": "models['1m']['peak'].predict(pandas.DataFrame([row], columns=meta['features']))[0]",
        },
    })


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    print("python", platform.python_version(), "sklearn", sklearn.__version__)
    train_scoring()
    train_forecast()
    train_antifraud()
