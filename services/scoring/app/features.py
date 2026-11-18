"""Признаки модели company-scoring-v1 (meta["feature_doc"]).

Имена должны совпадать с meta["features"] — Scoring передаёт их в ML Model по имени:
  companyAgeMonths       полных месяцев с RegistrationDate (СПАРК) до даты расчёта
  mainActivityCode       код ОКВЭД строкой вида '62.01'
  status                 ACTIVE | LIQUIDATING | LIQUIDATED
  groupSize              компаний в группе, ВКЛЮЧАЯ саму компанию (0, если группы нет)
  groupBankClientsCount  сколько ДРУГИХ компаний группы — клиенты банка (саму компанию не считаем)
"""
from datetime import date


def full_months(reg_date: date, as_of: date) -> int:
    months = (as_of.year - reg_date.year) * 12 + (as_of.month - reg_date.month)
    if as_of.day < reg_date.day:
        months -= 1
    return max(months, 0)


def build_features(company: dict, members: list[dict] | None, as_of: date | None = None):
    """company: {inn, reg_date: date, okved: str, status: str}
    members: участники группы, включая саму компанию: [{inn, is_bank_client: bool}] или None/[] без группы.
    Возвращает (numeric, categorical) для PredictRequest."""
    as_of = as_of or date.today()
    members = members or []
    group_size = len(members)
    bank_others = sum(1 for m in members if m["inn"] != company["inn"] and m.get("is_bank_client"))
    numeric = {
        # нет даты регистрации, то есть возраст просто 0 (иначе упадём с 500)
        "companyAgeMonths": float(full_months(company["reg_date"], as_of)) if company.get("reg_date") else 0.0,
        "groupSize": float(group_size),
        "groupBankClientsCount": float(bank_others),
    }
    categorical = {
        "mainActivityCode": company["okved"],
        "status": company["status"],
    }
    return numeric, categorical
