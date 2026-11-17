"""Первичная загрузка 1000 компаний и групп (владелец: Данияр).

1. Список всех ИНН (все страницы). Пустой список = ошибка, а не "всё загружено".
2. Пропускаем ИНН, у которых уже есть текущая версия: так загрузка продолжается после падения.
3. Пул из LOADER_WORKERS потоков: отчёт + группа -> store.save (scd2.upsert_group / scd2.upsert_company).
   Все потоки ждут один RateLimiter, поэтому 5 запросов/с не превышаем.
4. Если часть компаний не загрузилась, ждём остальных и падаем с LoadIncomplete и списком ИНН.
   Следующая попытка пройдёт только по недостающим.
5. В конце пишем load_state: initial_loaded_at, last_sync_at, initial_versions, initial_done (последним).

Клиент и хранилище передаются снаружи (по умолчанию Postgres), поэтому модуль тестируется без zeep и БД.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import spark_parse
from .metrics import COMPANIES, COMPANY_DURATION, observe_run
from .spark_errors import AuthFailed, LoadIncomplete, SkipCompany
from .store import PgStore

log = logging.getLogger("loader")

progress = {"total": 0, "done": 0, "skipped": 0, "failed": 0, "failed_sample": []}   # показываем в GET /status
_plock = threading.Lock()


def initial_progress() -> dict:
    with _plock:
        return progress.copy()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BatchResult:
    created: list = field(default_factory=list)   # ИНН, у которых появилась новая версия
    ok: int = 0
    skipped: list = field(default_factory=list)   # СПАРК не знает такой ИНН
    failed: list = field(default_factory=list)    # [(ИНН, ошибка)]


def fetch_row(client, inn: str):
    """Отчёт (+ группа, если в отчёте есть GroupId) -> (строка для SCD2, название группы, ActualDate).
    None, если СПАРК не знает компанию."""
    try:
        report = client.get_company_short_report(inn)
    except SkipCompany as e:
        log.warning("ИНН %s пропущен: %s", inn, e)
        return None
    group = None
    if spark_parse.has_group(report):      # у компании без группы лишний запрос не нужен
        try:
            group = client.get_company_group(inn)
        except SkipCompany:
            group = None                   # отчёт про группу знает, а группа нет: компанию всё равно не теряем
    row = spark_parse.to_company_row(report, group, inn)
    spark_parse.check_row(row, report)
    return row, spark_parse.group_name_of(group), spark_parse.actual_date_of(report)


def process_inns(client, store, inns: list, now: datetime, workers: int = 8, valid_from_actual: bool = True,
                 *, track_initial_progress: bool = False) -> BatchResult:
    result = BatchResult()

    @COMPANY_DURATION.time()
    def work(inn):
        try:
            fetched = fetch_row(client, inn)
            if fetched is None:
                COMPANIES.labels("skipped").inc()
                return None
            row, group_name, actual_date = fetched
            valid_from = actual_date if valid_from_actual and actual_date else now
            created = store.save(row, group_name, valid_from)
        except Exception:
            COMPANIES.labels("failed").inc()
            raise
        COMPANIES.labels("created" if created else "unchanged").inc()
        return created

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, inn): inn for inn in inns}
        for n, fut in enumerate(as_completed(futures), 1):
            inn = futures[fut]
            try:
                outcome = fut.result()
            except AuthFailed:
                for f in futures:      # логин неверный: незачем гонять остальные запросы
                    f.cancel()
                raise
            except Exception as err:   # одна плохая запись не должна останавливать остальные
                result.failed.append((inn, err))
                log.warning("ИНН %s не загружен: %s", inn, err)
                if track_initial_progress:
                    with _plock:
                        progress["failed"] += 1
                        progress["failed_sample"] = [i for i, _ in result.failed[:20]]
            else:
                if outcome is None:
                    result.skipped.append(inn)
                    if track_initial_progress:
                        with _plock:
                            progress["skipped"] += 1
                else:
                    result.ok += 1
                    if outcome:
                        result.created.append(inn)
                    if track_initial_progress:
                        with _plock:
                            progress["done"] += 1
            if n % 100 == 0:
                log.info("обработано %d из %d", n, len(inns))
    return result


def failed_message(prefix: str, result: BatchResult, total: int) -> str:
    sample = "; ".join(f"{inn}: {type(err).__name__}: {err}" for inn, err in result.failed[:5])
    return f"{prefix}: не загружено {len(result.failed)} из {total}. Например: {sample}"


@observe_run("initial")
def initial_load(client, store=None, workers: int = 8, valid_from_actual: bool = True):
    store = store or PgStore()
    # время начала берём от ПЕРВОГО запуска, чтобы после падения оно не сдвигалось
    started = store.get_state("initial_started_at")
    if started is None:
        started = utc_now().isoformat()
        store.set_state("initial_started_at", started)
    started_dt = datetime.fromisoformat(started)
    t0 = time.monotonic()

    all_inns = client.get_all_inns()
    if not all_inns:
        raise RuntimeError("СПАРК вернул пустой список компаний: проверь GetCompanyList и разбор (spark_parse.find_list)")
    have = store.current_inns()
    todo = [inn for inn in all_inns if inn not in have]
    with _plock:
        progress.update(total=len(all_inns), done=len(all_inns) - len(todo), skipped=0, failed=0, failed_sample=[])
    log.info("первичная загрузка: всего %d, уже есть %d, грузим %d", len(all_inns), len(have), len(todo))

    result = process_inns(client, store, todo, started_dt, workers, valid_from_actual,
                          track_initial_progress=True)
    if result.failed:
        raise LoadIncomplete(failed_message("первичная загрузка", result, len(todo)))

    versions = store.counts()["versions"]
    store.set_state("initial_loaded_at", started)
    store.set_state("last_sync_at", started)
    store.set_state("initial_versions", str(versions))
    store.set_state("initial_skipped", str(len(result.skipped)))
    store.set_state("initial_duration_sec", str(round(time.monotonic() - t0, 1)))
    store.set_state("initial_done", "true")    # последним: по нему ждут Enrichment и demo.sh
    log.info("первичная загрузка завершена: %s, пропущено (нет в СПАРК) %d", store.counts(), len(result.skipped))
