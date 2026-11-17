"""Инкремент (владелец: Данияр): GetChangedCompanies(Since=last_sync_at) -> отчёт + группа -> SCD2.

last_sync_at = время НАЧАЛА запроса, а не конца: иначе потеряем изменения,
которые пришли, пока шёл запрос. При ошибке курсор не двигаем: следующий проход повторит всё.
"""
import logging
import threading
from datetime import datetime

from .loader import failed_message, process_inns, utc_now
from .metrics import observe_run
from .spark_errors import LoadIncomplete
from .store import PgStore

log = logging.getLogger("incremental")

sync_lock = threading.Lock()   # расписание и POST /sync не должны идти одновременно


@observe_run("incremental")
def incremental_load(client, store=None, workers: int = 8, valid_from_actual: bool = True) -> dict:
    store = store or PgStore()
    with sync_lock:
        last = store.get_state("last_sync_at")
        if not last:
            raise LoadIncomplete("первичная загрузка ещё не закончена (нет last_sync_at)")
        since = datetime.fromisoformat(last)
        started = utc_now()
        inns = client.get_changed_companies(since)
        result = process_inns(client, store, inns, started, workers, valid_from_actual)
        # версии, которые успели появиться, запоминаем в любом случае: при повторе они будут "без изменений"
        store.add_changed_inns(result.created)
        if result.failed:
            raise LoadIncomplete(failed_message("инкремент", result, len(inns)))
        store.set_state("last_sync_at", started.isoformat())   # только после успешной обработки
    log.info("инкремент с %s: изменено %d, новых версий %d", since.isoformat(), len(inns), len(result.created))
    return {"changed": len(inns), "created": len(result.created), "skipped": len(result.skipped),
            "since": since.isoformat(), "last_sync_at": started.isoformat()}
