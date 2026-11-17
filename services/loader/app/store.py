"""Хранилище Loader: Postgres (боевой режим) или память (LOADER_DRY_RUN=true, БД не нужна).

Dry-run нужен, чтобы проверить загрузку и разбор ответов СПАРК до готовности scd2.py:
грузим все компании в память и смотрим /status (должно быть 1000 компаний и 73 группы)."""
import json
import logging

log = logging.getLogger("loader.store")


def merge_changed_inns(inns: list[str], previous: list[str], keep: int = 100) -> list[str]:
    return list(dict.fromkeys(inns + previous))[:keep]


class PgStore:
    def get_state(self, key):
        from . import db
        return db.get_state(key)

    def set_state(self, key, value):
        from . import db
        db.set_state(key, value)

    def current_inns(self) -> set:
        from . import db
        return db.current_inns()

    def counts(self) -> dict:
        from . import db
        return db.counts()

    def add_changed_inns(self, inns: list):
        from . import db
        db.add_changed_inns(inns)

    def save(self, row: dict, group_name, now) -> bool:
        """Одна транзакция: группа + компания. True, если появилась новая версия (решает scd2)."""
        from . import db, scd2
        with db.connect() as conn:
            if row.get("group_id"):
                scd2.upsert_group(conn, row["group_id"], group_name)
            return bool(scd2.upsert_company(conn, row, now))


class DryRunStore:
    def __init__(self):
        self.state, self.rows, self.group_ids = {}, {}, set()

    def get_state(self, key):
        return self.state.get(key)

    def set_state(self, key, value):
        self.state[key] = value

    def current_inns(self) -> set:
        return set(self.rows)

    def counts(self) -> dict:
        return {"companies": len(self.rows), "versions": len(self.rows), "groups": len(self.group_ids)}

    def add_changed_inns(self, inns: list, keep: int = 100):
        if inns:
            old = json.loads(self.state.get("changed_inns") or "[]")
            self.state["changed_inns"] = json.dumps(merge_changed_inns(list(inns), old, keep))

    def save(self, row: dict, group_name, now) -> bool:
        changed = self.rows.get(row["inn"]) != row
        self.rows[row["inn"]] = row
        if row.get("group_id"):
            self.group_ids.add(row["group_id"])
        return changed


def make_store(dry_run: bool):
    if dry_run:
        log.warning("LOADER_DRY_RUN=true: в БД ничего не пишем, данные только в памяти")
        return DryRunStore()
    return PgStore()
