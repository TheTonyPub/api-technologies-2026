"""SOAP-клиент СПАРК на zeep (владелец: Данияр).

- authenticate() при старте, SessionId передаём в SOAP-заголовке;
- SESSION_EXPIRED / AUTH_REQUIRED: логинимся заново (один раз на вызов) и повторяем запрос;
- перед КАЖДЫМ вызовом ждём общий RateLimiter (5 запросов/с на всю команду);
- RATE_LIMIT, другие SOAP Fault, HTTP 429/503, 5xx, таймауты: повтор с экспоненциальной паузой
  (на 429/503 учитываем заголовок Retry-After); после последней попытки не спим;
- INVALID_REQUEST / UNKNOWN_OPERATION: сразу SparkBadRequest, это наша ошибка, повторять бесполезно;
- AUTH_FAILED не глотаем: бросаем AuthFailed, main.py громко пишет в лог;
- COMPANY_NOT_FOUND и INVALID_INN: бросаем SkipCompany, загрузчик пропускает одну запись;
- zeep.Client не потокобезопасен, поэтому у каждого потока свой клиент (WSDL качается один раз и кэшируется);
- пароль в лог не пишем, в тексте ошибок есть операция и ИНН.

Имена операций и параметров собраны в блоке ниже. Сверить с WSDL:
    python -m zeep https://api.external-services.dataprosvet.ru/spark/ws?wsdl
или запустить scripts/spark_probe.py.
"""
import logging
import threading
import time
from datetime import datetime

import requests
import zeep
from lxml import etree
from zeep.cache import InMemoryCache
from zeep.exceptions import Fault, TransportError
from zeep.helpers import serialize_object
from zeep.transports import Transport

from . import spark_parse
from .config import settings
from .metrics import SOAP_RETRIES
from .rate_limiter import RateLimiter
from .spark_errors import AuthFailed, SkipCompany, SparkBadRequest, SparkUnavailable  # noqa: F401 (реэкспорт)

log = logging.getLogger("spark")

# ---- имена из WSDL (если в WSDL иначе, поправить только здесь) ----
OP_AUTH = "Authenticate"
OP_LIST = "GetCompanyList"
OP_REPORT = "GetCompanyShortReport"
OP_GROUP = "GetCompanyGroup"
OP_CHANGED = "GetChangedCompanies"
HEADER_SESSION = "SessionId"      # элемент SOAP-заголовка
P_PAGE, P_PAGE_SIZE, P_INN, P_SINCE = "Page", "PageSize", "INN", "Since"   # из WSDL: INN заглавными
# -------------------------------------------------------------------

MAX_ATTEMPTS = 6
SKIP_CODES = ("COMPANY_NOT_FOUND", "INVALID_INN")
SESSION_CODES = ("SESSION_EXPIRED", "AUTH_REQUIRED")
BAD_CODES = ("INVALID_REQUEST", "UNKNOWN_OPERATION")
KNOWN_CODES = SESSION_CODES + ("RATE_LIMIT", "AUTH_FAILED") + BAD_CODES + SKIP_CODES

limiter = RateLimiter(settings.rate_limit_rps)   # один на весь процесс, его ждут все потоки
_WSDL_CACHE = InMemoryCache()                    # WSDL качаем один раз, а не по разу на поток


class RetryLater(Exception):
    """HTTP 429 или 503 от мока."""
    def __init__(self, status: int, retry_after: str | None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


class _Transport(Transport):
    """Сохраняем Retry-After, в том числе для недоступности в SOAP Fault с HTTP 500."""
    def post(self, address, message, headers):
        response = super().post(address, message, headers)
        retry_after = response.headers.get("Retry-After")
        if response.status_code in (429, 503) or (response.status_code == 500 and retry_after):
            raise RetryLater(response.status_code, retry_after)
        return response


def fault_code(fault: Fault) -> str:
    """Наш код ошибки (SESSION_EXPIRED и т.п.): сначала detail/.../ErrorCode, потом поиск по тексту Fault."""
    detail = getattr(fault, "detail", None)
    if detail is not None:
        for el in detail.iter():
            if isinstance(el.tag, str) and el.tag.split("}")[-1] == "ErrorCode":
                value = (el.text or "").strip().upper()
                if value:
                    return value
    parts = [str(getattr(fault, "message", "") or ""), str(getattr(fault, "code", "") or "")]
    if detail is not None:
        parts.append(etree.tostring(detail, encoding="unicode"))
    text = " ".join(parts).upper()
    for code in KNOWN_CODES:
        if code in text:
            return code
    return "FAULT"


def backoff(attempt: int) -> float:
    return min(2 ** attempt, 30)          # 1, 2, 4, 8, 16, 30 секунд


def pause_for(err: RetryLater, attempt: int) -> float:
    try:
        return min(max(float(err.retry_after), 0.5), 60.0)
    except (TypeError, ValueError):
        return backoff(attempt)


def _describe(op: str, params: dict) -> str:
    safe = {k: v for k, v in params.items() if k != "Password"}
    return f"{op}{safe}"


class SparkClient:
    def __init__(self):
        self._local = threading.local()
        self._auth_lock = threading.Lock()
        self.session_id = None
        self.ns = settings.spark_ns or None
        self._svc()          # в основном потоке: ошибки WSDL/binding видны сразу при старте

    # ---------- служебное ----------

    @staticmethod
    def _pick_binding(client) -> str:
        bindings = client.wsdl.bindings            # ключи вида "{namespace}ИмяBinding"
        for name, binding in bindings.items():
            if type(binding).__name__ == "Soap11Binding":
                return name
        return next(iter(bindings))

    def _svc(self):
        """Сервис zeep текущего потока (создаётся при первом обращении)."""
        service = getattr(self._local, "service", None)
        if service is None:
            session = requests.Session()
            if settings.mock_scenario:        # заголовок только если переменная задана
                session.headers["X-Mock-Scenario"] = settings.mock_scenario
            transport = _Transport(session=session, cache=_WSDL_CACHE, timeout=settings.request_timeout,
                                   operation_timeout=settings.request_timeout)
            client = zeep.Client(settings.spark_wsdl, transport=transport)
            binding = self._pick_binding(client)
            # ходим по адресу из SPARK_URL, а не по тому, что записан в WSDL
            service = client.create_service(binding, settings.spark_url)
            if self.ns is None:
                self.ns = binding[1:binding.index("}")]
            self._local.service = service
        return service

    def _soap_header(self):
        el = etree.Element(etree.QName(self.ns, HEADER_SESSION))
        el.text = self.session_id
        return [el]

    # ---------- сессия ----------

    def authenticate(self):
        with self._auth_lock:
            self._login()

    def _relogin(self, used_session):
        """Один поток логинится заново, остальные видят уже новую сессию и ничего не делают."""
        with self._auth_lock:
            if self.session_id != used_session:
                return
            self._login()

    def _login(self):
        result = self._request(OP_AUTH, {"Login": settings.spark_login, "Password": settings.spark_password},
                               with_session=False)
        sid = result if isinstance(result, str) else spark_parse.pick(result, "SessionId", "Session")
        if not sid:
            raise SparkUnavailable("Authenticate не вернул SessionId")
        self.session_id = str(sid)
        log.info("авторизация в СПАРК успешна")   # пароль и SessionId не логируем

    # ---------- вызов с повторами ----------

    def _request(self, op: str, params: dict, with_session: bool = True):
        """Один вызов операции: лимит частоты, повторы, перелогин. Возвращает обычные dict/list."""
        relogged = False
        last = "нет данных"
        for attempt in range(MAX_ATTEMPTS):
            if with_session and self.session_id is None:
                self._relogin(None)
            used_session = self.session_id
            limiter.wait()
            try:
                kwargs = dict(params)
                if with_session:
                    kwargs["_soapheaders"] = self._soap_header()
                return serialize_object(self._svc()[op](**kwargs), dict)
            except Fault as f:
                code = fault_code(f)
                what = _describe(op, params)
                if code == "AUTH_FAILED":
                    raise AuthFailed("СПАРК: неверный SPARK_LOGIN или SPARK_PASSWORD") from None
                if code in SKIP_CODES:
                    raise SkipCompany(f"{what}: {code}") from None
                if code in BAD_CODES:
                    raise SparkBadRequest(f"{what}: {code}. Проверь имена операции и параметров по WSDL") from None
                if code in SESSION_CODES and with_session and not relogged:
                    log.info("%s: %s, логинимся заново", op, code)
                    relogged = True
                    self._relogin(used_session)
                    continue
                pause, last = backoff(attempt), f"SOAP Fault {code} ({f.message})"
            except RetryLater as e:
                pause, last = pause_for(e, attempt), str(e)
            except (TransportError, requests.RequestException) as e:   # 5xx, таймаут, нет соединения
                pause, last = backoff(attempt), f"{type(e).__name__}: {e}"
            log.warning("%s: %s, попытка %d из %d", _describe(op, params), last, attempt + 1, MAX_ATTEMPTS)
            if attempt < MAX_ATTEMPTS - 1:
                SOAP_RETRIES.labels(op).inc()
                time.sleep(pause)
        raise SparkUnavailable(f"{_describe(op, params)}: не удалось после {MAX_ATTEMPTS} попыток, последняя причина: {last}")

    # ---------- операции ----------

    def _page_params(self, page: int) -> dict:
        params = {P_PAGE: page}
        if settings.spark_page_size:
            params[P_PAGE_SIZE] = settings.spark_page_size
        return params

    def get_company_list(self, page: int):
        return self._request(OP_LIST, self._page_params(page))

    def _collect_pages(self, op: str, extra: dict | None = None, max_pages: int = 1000) -> list:
        """Все записи постраничной операции (список компаний, список изменений).
        Ответ вида {"Total": N, "Page": 1, "Companies": {"Company": [...]}}: Total это число записей во всех страницах.
        Если сервер заявил Total, неполный результат считается ошибкой.
        Для списка компаний без Total повтор страницы сохраняет прежнее поведение."""
        items_all, seen_pages, paged = [], set(), True
        expected_total = None
        for page in range(1, max_pages + 1):
            params = dict(extra or {})
            if paged:
                params.update(self._page_params(page))
            try:
                resp = self._request(op, params)
            except TypeError as e:
                if not paged or "unexpected keyword" not in str(e):
                    raise
                log.warning("у %s нет параметра %s, берём ответ целиком", op, P_PAGE)
                paged, resp = False, self._request(op, dict(extra or {}))
            items = spark_parse.find_list(resp)
            total = spark_parse.pick(resp, "Total", "TotalCount")
            if total is not None:
                try:
                    total = int(total)
                except (TypeError, ValueError, OverflowError):
                    raise SparkUnavailable(f"{op}: некорректный Total в ответе") from None
                if total < 0:
                    raise SparkUnavailable(f"{op}: отрицательный Total в ответе")
                expected_total = total if expected_total is None else max(expected_total, total)
            signature = repr(items)
            repeated = signature in seen_pages
            if repeated and expected_total is None and op == OP_CHANGED:
                raise SparkUnavailable(f"{op}: повтор страницы {page} без Total")
            if not items or repeated:
                break
            seen_pages.add(signature)
            items_all += items
            if not paged:
                break
            if expected_total is not None and len(items_all) >= expected_total:
                break
        else:
            raise SparkUnavailable(f"{op}: достигнут лимит страниц ({max_pages})")
        if expected_total is not None and len(items_all) < expected_total:
            raise SparkUnavailable(f"{op}: получено {len(items_all)} записей из {expected_total}")
        return items_all

    def get_all_inns(self, max_pages: int = 1000) -> list[str]:
        """Все ИНН компаний из GetCompanyList (все страницы)."""
        items = self._collect_pages(OP_LIST, max_pages=max_pages)
        inns = list(dict.fromkeys(i for i in map(spark_parse.inn_of, items) if i))
        log.info("список компаний: %d ИНН", len(inns))
        return inns

    def get_company_short_report(self, inn: str):
        return self._request(OP_REPORT, {P_INN: inn})

    def get_company_group(self, inn: str):
        return self._request(OP_GROUP, {P_INN: inn})

    def get_changed_companies(self, since: datetime) -> list[str]:
        """ИНН компаний, изменившихся с момента since (все страницы; у одной компании может быть несколько изменений)."""
        items = self._collect_pages(OP_CHANGED, {P_SINCE: since})
        return list(dict.fromkeys(i for i in map(spark_parse.inn_of, items) if i))
