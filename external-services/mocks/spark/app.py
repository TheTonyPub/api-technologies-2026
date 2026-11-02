"""Мок СПАРК (SOAP 1.1). Путь на сервере: /spark, сервис — /spark/ws, WSDL — /spark/ws?wsdl."""

from __future__ import annotations

import asyncio
import os
import random
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from lxml import etree

from ..common import companies
from ..common import reference as ref
from ..common.core import ApiError, ErrorStyle, RateLimiter, create_app
from .wsdl import NS, OPERATIONS, render_wsdl

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
PUBLIC_URL = os.getenv("SPARK_PUBLIC_URL", "https://api.external-services.dataprosvet.ru/spark/ws")
SESSION_TTL = timedelta(minutes=int(os.getenv("SPARK_SESSION_MINUTES", "30")))
REPORT_LATENCY = (0.5, 2.0) if os.getenv("SPARK_LATENCY", "on") == "on" else (0, 0)


def load_users() -> dict[str, tuple[str, str]]:
    """SPARK_USERS="team:login:password,..." -> {login: (password, team)}."""
    out = {}
    for item in os.getenv("SPARK_USERS", "demo:demo:demo").split(","):
        parts = item.strip().split(":")
        if len(parts) == 3:
            out[parts[1]] = (parts[2], parts[0])
    return out


USERS = load_users()
SESSIONS: dict[str, tuple[str, datetime]] = {}
_lock = threading.Lock()
limiter = RateLimiter(int(os.getenv("SPARK_RPS", "5")))


def soap_fault(code: str, message: str, client_side: bool = True) -> bytes:
    env = etree.Element(etree.QName(SOAP_NS, "Envelope"), nsmap={"soap": SOAP_NS, "spk": NS})
    body = etree.SubElement(env, etree.QName(SOAP_NS, "Body"))
    fault = etree.SubElement(body, etree.QName(SOAP_NS, "Fault"))
    etree.SubElement(fault, "faultcode").text = "soap:Client" if client_side else "soap:Server"
    etree.SubElement(fault, "faultstring").text = message
    detail = etree.SubElement(fault, "detail")
    sf = etree.SubElement(detail, etree.QName(NS, "SparkFault"))
    etree.SubElement(sf, etree.QName(NS, "ErrorCode")).text = code
    etree.SubElement(sf, etree.QName(NS, "Message")).text = message
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


class SoapStyle(ErrorStyle):
    def render(self, request, err: ApiError):
        client_side = err.status < 500 and err.status != 429
        headers = dict(err.headers)
        return Response(soap_fault(err.code, err.message, client_side), status_code=500 if err.status != 429 else 429,
                        media_type="text/xml; charset=utf-8", headers=headers)


DESCRIPTION = (
    "Учебный SOAP-сервис по мотивам СПАРК-Интерфакс (не настоящий API и не его копия). "
    "**Кому нужен:** кейс «СПАРК» — Loader загружает карточки юрлиц и группы компаний и пишет их в SCD2. "
    "Описание и примеры: `GET /spark/`, WSDL: `GET /spark/ws?wsdl`."
)
app = create_app("Мок СПАРК (SOAP)", DESCRIPTION, style=SoapStyle())


def q(name: str) -> etree.QName:
    return etree.QName(NS, name)


def sub(parent, name: str, text=None, nil=False):
    el = etree.SubElement(parent, q(name))
    if nil:
        el.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
    elif text is not None:
        el.text = str(text)
    return el


def envelope(op: str):
    env = etree.Element(etree.QName(SOAP_NS, "Envelope"),
                        nsmap={"soap": SOAP_NS, "spk": NS, "xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    body = etree.SubElement(env, etree.QName(SOAP_NS, "Body"))
    return env, etree.SubElement(body, q(f"{op}Response"))


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> datetime:
    return datetime.now(timezone.utc)


def text(el, name: str, required=True) -> str | None:
    found = el.find(q(name))
    if found is None or found.text is None or not found.text.strip():
        if required:
            raise ApiError(400, "INVALID_REQUEST", f"Не передан элемент {name}")
        return None
    return found.text.strip()


def int_param(el, name: str, default: int, lo: int, hi: int) -> int:
    v = text(el, name, required=False)
    if v is None:
        return default
    try:
        x = int(v)
    except ValueError:
        raise ApiError(400, "INVALID_REQUEST", f"{name} должен быть целым числом")
    if not lo <= x <= hi:
        raise ApiError(400, "INVALID_REQUEST", f"{name} должен быть от {lo} до {hi}")
    return x


def company_by_inn(inn: str | None) -> int:
    if not inn or not inn.isdigit() or len(inn) != 10 or not companies.is_valid_inn(inn):
        raise ApiError(400, "INVALID_INN", f"Неверный ИНН юрлица: {inn!r} (10 цифр с верной контрольной суммой)")
    idx = companies.universe()[2].get(inn)
    if idx is None:
        raise ApiError(404, "COMPANY_NOT_FOUND", f"Компания с ИНН {inn} не найдена")
    return idx


def check_session(header) -> str:
    sid = None
    if header is not None:
        el = header.find(q("SessionId"))
        sid = el.text.strip() if el is not None and el.text else None
    if not sid:
        raise ApiError(401, "AUTH_REQUIRED", "Нужен SessionId в SOAP Header: сначала вызовите Authenticate")
    with _lock:
        s = SESSIONS.get(sid)
    if not s:
        raise ApiError(401, "AUTH_REQUIRED", "Неизвестный SessionId: вызовите Authenticate")
    team, expires = s
    if now() > expires:
        raise ApiError(401, "SESSION_EXPIRED", "Сессия истекла: вызовите Authenticate ещё раз")
    limiter.check(team)
    return team


async def slow():
    if REPORT_LATENCY[1]:
        await asyncio.sleep(random.uniform(*REPORT_LATENCY))


# ---------------------------------------------------------------- операции

def op_authenticate(req) -> bytes:
    login, password = text(req, "Login"), text(req, "Password")
    u = USERS.get(login)
    if not u or not secrets.compare_digest(u[0], password):
        raise ApiError(401, "AUTH_FAILED", "Неверный логин или пароль")
    sid = secrets.token_hex(16)
    expires = now() + SESSION_TTL
    with _lock:
        for k in [k for k, (_, e) in SESSIONS.items() if e < now()]:
            del SESSIONS[k]
        SESSIONS[sid] = (u[1], expires)
    env, resp = envelope("Authenticate")
    sub(resp, "SessionId", sid)
    sub(resp, "ExpiresAt", iso(expires))
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


def op_company_list(req) -> bytes:
    page = int_param(req, "Page", 1, 1, 10_000)
    size = int_param(req, "PageSize", 100, 1, 500)
    t = now()
    all_c = companies.universe()[0]
    env, resp = envelope("GetCompanyList")
    sub(resp, "Total", len(all_c))
    sub(resp, "Page", page)
    lst = sub(resp, "Companies")
    for c in all_c[(page - 1) * size: page * size]:
        st = companies.company_at(c.idx, t)
        item = sub(lst, "Company")
        sub(item, "INN", st.inn)
        sub(item, "ShortName", st.short_name)
        sub(item, "Status", st.status)
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


def op_short_report(req) -> bytes:
    idx = company_by_inn(text(req, "INN", required=False))
    c = companies.company_at(idx, now())
    env, resp = envelope("GetCompanyShortReport")
    el = sub(resp, "Company")
    for name, value in [("INN", c.inn), ("OGRN", c.ogrn), ("KPP", c.kpp), ("ShortName", c.short_name),
                        ("FullName", c.full_name), ("Status", c.status),
                        ("RegistrationDate", c.registration_date.isoformat()), ("RegionCode", c.region_code),
                        ("LegalAddress", c.legal_address)]:
        sub(el, name, value)
    ok = sub(el, "OKVED")
    sub(ok, "Code", c.okved)
    sub(ok, "Name", ref.OKVED[c.okved])
    sub(el, "AuthorizedCapital", c.authorized_capital)
    sub(el, "EmployeeCount", c.employees)
    head = sub(el, "Head")
    sub(head, "FullName", c.head_name)
    sub(head, "Position", c.head_position)
    sub(el, "GroupId", c.group_id, nil=c.group_id is None)
    sub(el, "Revision", c.revision)
    sub(el, "ActualDate", iso(c.actual_date))
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


def op_group(req) -> bytes:
    idx = company_by_inn(text(req, "INN", required=False))
    t = now()
    c = companies.company_at(idx, t)
    env, resp = envelope("GetCompanyGroup")
    if c.group_id is None:
        sub(resp, "GroupId", nil=True)
        sub(resp, "GroupName", nil=True)
        sub(resp, "Members")
    else:
        grp = companies.universe()[1][c.group_id]
        sub(resp, "GroupId", grp.group_id)
        sub(resp, "GroupName", grp.name)
        members = sub(resp, "Members")
        for st, role, share in companies.group_members_at(c.group_id, t):
            m = sub(members, "Member")
            sub(m, "INN", st.inn)
            sub(m, "ShortName", st.short_name)
            sub(m, "Role", role)
            sub(m, "SharePercent", share)
            sub(m, "Status", st.status)
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


def op_changed(req) -> bytes:
    raw = text(req, "Since")
    try:
        since = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(400, "INVALID_REQUEST", "Since должен быть в формате xsd:dateTime, например 2026-10-01T00:00:00Z")
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    page = int_param(req, "Page", 1, 1, 10_000)
    size = int_param(req, "PageSize", 100, 1, 500)
    t = now()
    if since < t - timedelta(days=90):
        raise ApiError(400, "INVALID_REQUEST", "Since не раньше чем 90 дней назад; для полной загрузки — GetCompanyList")
    changes = companies.changes_between(since, t)
    all_c = companies.universe()[0]
    env, resp = envelope("GetChangedCompanies")
    sub(resp, "Total", len(changes))
    sub(resp, "Page", page)
    lst = sub(resp, "Changes")
    for ch in changes[(page - 1) * size: page * size]:
        item = sub(lst, "Change")
        sub(item, "INN", all_c[ch.idx].inn)
        sub(item, "ChangedAt", iso(ch.ts))
        sub(item, "ChangeType", ch.kind)
    return etree.tostring(env, xml_declaration=True, encoding="utf-8")


HANDLERS = {"Authenticate": op_authenticate, "GetCompanyList": op_company_list,
            "GetCompanyShortReport": op_short_report, "GetCompanyGroup": op_group,
            "GetChangedCompanies": op_changed}
SLOW_OPS = {"GetCompanyShortReport", "GetCompanyGroup"}


@app.get("/ws", include_in_schema=False)
async def wsdl(request: Request):
    if "wsdl" not in {k.lower() for k in request.query_params}:
        raise ApiError(404, "NOT_FOUND", "Для WSDL откройте /spark/ws?wsdl, запросы — POST /spark/ws")
    return Response(render_wsdl(PUBLIC_URL), media_type="text/xml; charset=utf-8")


@app.post("/ws", include_in_schema=False)
async def soap(request: Request):
    raw = await request.body()
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        env = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError:
        raise ApiError(400, "INVALID_REQUEST", "Тело запроса не XML")
    if env.tag != etree.QName(SOAP_NS, "Envelope"):
        raise ApiError(400, "INVALID_REQUEST", "Ожидается SOAP 1.1 Envelope (http://schemas.xmlsoap.org/soap/envelope/)")
    body = env.find(etree.QName(SOAP_NS, "Body"))
    if body is None or len(body) == 0:
        raise ApiError(400, "INVALID_REQUEST", "Пустой soap:Body")
    req = body[0]
    qn = etree.QName(req)
    if qn.namespace != NS or qn.localname not in HANDLERS:
        raise ApiError(400, "UNKNOWN_OPERATION",
                       f"Неизвестная операция {qn.localname} (namespace {qn.namespace}). Доступны: {', '.join(OPERATIONS)}")
    if qn.localname != "Authenticate":
        check_session(env.find(etree.QName(SOAP_NS, "Header")))
    if qn.localname in SLOW_OPS:
        await slow()
    return Response(HANDLERS[qn.localname](req), media_type="text/xml; charset=utf-8")


EXAMPLE_AUTH = """<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:spk="urn:mock:spark:v1">
  <soap:Body>
    <spk:Authenticate><spk:Login>ЛОГИН</spk:Login><spk:Password>ПАРОЛЬ</spk:Password></spk:Authenticate>
  </soap:Body>
</soap:Envelope>"""

EXAMPLE_REPORT = """<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:spk="urn:mock:spark:v1">
  <soap:Header><spk:SessionId>SESSION_ID</spk:SessionId></soap:Header>
  <soap:Body>
    <spk:GetCompanyShortReport><spk:INN>{inn}</spk:INN></spk:GetCompanyShortReport>
  </soap:Body>
</soap:Envelope>"""


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
async def index():
    from html import escape
    inn = companies.universe()[0][0].inn
    ops = "".join(f"<li><code>{o}</code></li>" for o in OPERATIONS)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Мок СПАРК</title>
<style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 16px;line-height:1.5}}
pre{{background:#f4f4f4;padding:12px;overflow:auto}}</style></head><body>
<h1>Мок СПАРК (SOAP 1.1)</h1>
<p>Учебный сервис по мотивам СПАРК-Интерфакс. Это не настоящий API Интерфакса и не его копия, все компании вымышленные.
Кейс «СПАРК»: Loader загружает карточки и группы компаний в SCD2.</p>
<ul><li>Адрес сервиса: <code>POST {escape(PUBLIC_URL)}</code></li>
<li>WSDL: <a href="ws?wsdl"><code>{escape(PUBLIC_URL)}?wsdl</code></a></li></ul>
<h2>Операции</h2><ul>{ops}</ul>
<p>Сессия живёт {int(SESSION_TTL.total_seconds() // 60)} минут, лимит {limiter.per_second} запросов/с.
Отчёты отвечают 0,5–2 с. Около 3% компаний меняются каждый день (адрес, руководитель, КПП, ОКВЭД, статус, группа):
изменения с момента <code>Since</code> отдаёт <code>GetChangedCompanies</code>.
Ошибки — SOAP Fault с <code>detail/SparkFault/ErrorCode</code>: AUTH_REQUIRED, AUTH_FAILED, SESSION_EXPIRED,
INVALID_INN, COMPANY_NOT_FOUND, RATE_LIMIT, INVALID_REQUEST, UNKNOWN_OPERATION.</p>
<h2>1. Получить сессию</h2><pre>{escape(EXAMPLE_AUTH)}</pre>
<h2>2. Запросить карточку</h2><pre>{escape(EXAMPLE_REPORT.format(inn=inn))}</pre>
<pre>curl -s -X POST {escape(PUBLIC_URL)} -H 'Content-Type: text/xml; charset=utf-8' --data @request.xml</pre>
</body></html>"""
