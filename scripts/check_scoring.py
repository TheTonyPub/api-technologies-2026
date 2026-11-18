#!/usr/bin/env python3
"""сверка скоринга (владелец: Фёдор)

для каждого ИНН берём скор через Gateway, потом сами собираем признаки из company_snapshot
(своим SQL, без features.py сервиса) и считаем скор напрямую файлом .dill.
сравниваем с допуском 1e-6, если хоть один не совпал, выходим с кодом 1

запускаем так (сервисы подняты, база на localhost:5432)
    pip install dill==0.4.0 pandas==2.3.3 scikit-learn==1.8.0 "psycopg[binary]"
    python scripts/check_scoring.py 9990000001 9990000011 9990000021

переменные те же, что у сервиса (GW, GATEWAY_TOKEN, DATABASE_URL, MODEL_PATH, SCORING_AS_OF)
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import dill
import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
GW = os.getenv("GW", "http://localhost:8000")
TOKEN = os.getenv("GATEWAY_TOKEN", "change-me")
DB = os.getenv("DATABASE_URL", "postgresql://spark:spark@localhost:5432/spark").replace("@postgres:", "@localhost:")
MODEL = os.getenv("MODEL_PATH", str(ROOT / "models" / "company-scoring-v1.dill"))
if not Path(MODEL).exists():          # в .env путь из контейнера (/models/...), а скрипт мы запускаем на хосте
    MODEL = str(ROOT / "models" / "company-scoring-v1.dill")
AS_OF = os.getenv("SCORING_AS_OF", "today")
TOLERANCE = 1e-6

# группу считаем прямо в SQL, то есть не через features.py сервиса
SQL = """
SELECT c.registration_date, c.okved_code, c.status, c.data_as_of,
       (SELECT count(*) FROM company_snapshot g WHERE g.group_id = c.group_id)              AS group_size,
       (SELECT count(*) FROM company_snapshot g
         WHERE g.group_id = c.group_id AND g.inn <> c.inn AND g.is_bank_client)              AS group_bank_others
FROM company_snapshot c WHERE c.inn = %s
"""


def score_via_gateway(inn: str) -> float:
    req = urllib.request.Request(f"{GW}/v1/companies/{inn}/scoring",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return float(json.load(r)["probability"])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gateway ответил {e.code}: {e.read().decode()}") from None


def months_between(start, end) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def features_from_db(conn, inn: str) -> dict:
    row = conn.execute(SQL, (inn,)).fetchone()
    if row is None:
        raise RuntimeError("нет в company_snapshot")
    reg_date, okved, status, data_as_of, group_size, bank_others = row
    as_of = data_as_of.astimezone(timezone.utc).date() if AS_OF == "data_as_of" else datetime.now(timezone.utc).date()
    return {
        "companyAgeMonths": float(months_between(reg_date, as_of)) if reg_date else 0.0,
        "mainActivityCode": okved,
        "status": status,
        "groupSize": float(group_size),            # нет группы, значит group_id NULL и count даёт 0
        "groupBankClientsCount": float(bank_others),
    }


def main():
    inns = sys.argv[1:] or ["9990000001", "9990000011", "9990000021"]
    with open(MODEL, "rb") as f:
        art = dill.load(f)
    model, columns = art["model"], list(art["meta"]["features"])
    print(f"модель: {MODEL}\nпризнаки: {columns}\nдата расчёта: {AS_OF}\n")

    ok = True
    with psycopg.connect(DB) as conn:
        for inn in inns:
            try:
                features = features_from_db(conn, inn)
                direct = float(model.predict_proba(pd.DataFrame([features], columns=columns))[0, 1])
                gateway = score_via_gateway(inn)
            except Exception as e:
                print(f"{inn}  ОШИБКА: {e}")
                ok = False
                continue
            diff = abs(direct - gateway)
            same = diff <= TOLERANCE
            ok = ok and same
            print(f"{inn}  gateway={gateway:.6f}  модель={direct:.6f}  разница={diff:.1e}  "
                  f"{'OK' if same else 'НЕ СОВПАЛО'}  {features}")

    print("\nвсё совпало" if ok else "\nесть расхождения")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
