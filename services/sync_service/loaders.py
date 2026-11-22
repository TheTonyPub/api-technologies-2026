"""Четыре загрузки сервиса синхронизации.

1. load_clients_and_accounts: клиенты и счета из /abs в PostgreSQL
2. load_transactions:         операции за 30 дней из /abs в PostgreSQL
3. load_profiles:             профили клиентов из /client-data в PostgreSQL
4. load_risks:                риски регионов и мерчантов из /client-data в Redis
"""
import logging
from datetime import datetime, timedelta, timezone

import config
import db
from http_client import ApiError

log = logging.getLogger("loaders")

PAGE_SIZE = 500  # максимум, который разрешает АБС
REDIS_REGION_KEY = "risk:region"  # hash: код региона -> geo_risk
REDIS_MERCHANT_KEY = "risk:merchant"  # hash: id мерчанта -> merchant_risk


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 1. клиенты и счета

def load_clients_and_accounts(abs_api, conn):
    # --- клиенты: идём по страницам, пока nextCursor не станет null
    account_ids = []
    clients_count = 0
    cursor = None
    while True:
        params = {"type": "individual", "limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        data = abs_api.get("/v1/clients", params)
        db.save_clients(conn, data["items"])
        for client in data["items"]:
            account_ids.extend(client["accounts"])
        clients_count += len(data["items"])
        cursor = data["nextCursor"]
        if not cursor:
            break
    log.info("клиентов загружено: %d", clients_count)

    # --- счета: в списке клиентов только номера счетов, детали берём по одному.
    # Те, что уже есть в базе, пропускаем. Так после падения загрузка продолжается с того же места.
    known = db.get_account_ids(conn)
    missing = [a for a in account_ids if a not in known]
    log.info("счетов всего %d, надо догрузить %d", len(account_ids), len(missing))

    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        accounts = []
        try:
            for account_id in chunk:
                try:
                    accounts.append(abs_api.get(f"/v1/accounts/{account_id}"))
                except ApiError as e:
                    if e.status == 404:  # такого счёта нет, пропускаем, остальные грузим
                        log.warning("счёт %s не найден, пропускаю", account_id)
                        continue
                    raise
        finally:
            # сохраняем всё, что успели получить, даже если дальше случилась ошибка
            if accounts:
                db.save_accounts(conn, accounts)
    log.info("счета загружены")


# ---------------------------------------------------------------- 2. операции за 30 дней

def load_transactions(abs_api, conn):
    # Куда мы дошли в прошлый раз? Если прошлый проход не закончился, tx_pass_to ещё лежит в базе.
    pass_to = db.get_state(conn, "tx_pass_to")
    if pass_to:
        from_ = db.get_state(conn, "tx_pass_from")
        to = pass_to
        cursor = db.get_state(conn, "tx_pass_cursor") or None
        log.info("продолжаю незаконченную загрузку операций, курсор: %s", cursor)
    else:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        window_start = now - timedelta(days=config.TX_DAYS)
        loaded_until = db.get_state(conn, "tx_loaded_until")
        if loaded_until:
            # обновление: берём с небольшим запасом, дубли отсечёт ON CONFLICT DO NOTHING
            start = parse_iso(loaded_until) - timedelta(hours=config.TX_OVERLAP_HOURS)
            start = max(start, window_start)
        else:
            start = window_start  # первая загрузка: все 30 дней
        from_, to, cursor = iso(start), iso(now), None
        db.save_transactions_page(conn, [], {"tx_pass_from": from_, "tx_pass_to": to, "tx_pass_cursor": ""})
        log.info("загружаю операции с %s по %s", from_, to)

    pages = 0
    received = 0
    while True:
        params = {"from": from_, "to": to, "limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        data = abs_api.get("/v1/transactions", params)
        cursor = data["nextCursor"]
        # операции и курсор сохраняются вместе, поэтому после падения можно продолжить с этого курсора
        db.save_transactions_page(conn, data["items"], {"tx_pass_cursor": cursor or ""})
        pages += 1
        received += len(data["items"])
        if not cursor:
            break
    db.finish_transactions_pass(conn, to)
    log.info("операции: страниц %d, получено %d", pages, received)

    # Запоминаем, сколько операций было после первой загрузки (пригодится для сверки с эталоном)
    if db.get_state(conn, "initial_tx_count") is None:
        db.set_state(conn, "initial_tx_count", str(db.count_transactions(conn)))

    # Окно сдвигается, поэтому операции старше 30 дней удаляем
    deleted = db.delete_old_transactions(conn, config.TX_DAYS)
    if deleted:
        log.info("удалено операций старше %d дней: %d", config.TX_DAYS, deleted)


# ---------------------------------------------------------------- 3. профили клиентов

def load_profiles(bureau_api, conn):
    client_ids = db.get_client_ids(conn)
    if not client_ids:
        log.warning("в базе нет клиентов, профили грузить не для кого")
        return

    found_total = 0
    not_found_total = 0
    for i in range(0, len(client_ids), 100):  # в одном запросе максимум 100 клиентов
        chunk = client_ids[i:i + 100]
        try:
            data = bureau_api.post("/v1/persons:batch", {"client_ids": chunk})
        except ApiError as e:
            if e.status != 404:
                raise
            # бюро ответило 404 на всю пачку: считаем, что о них нет данных
            data = {"items": [], "not_found": chunk}
        # о части клиентов бюро ничего не знает: они приходят в списке not_found
        db.save_profiles(conn, data["items"], data["not_found"])
        found_total += len(data["items"])
        not_found_total += len(data["not_found"])
    log.info("профили: найдено %d, не найдено в бюро %d", found_total, not_found_total)


# ---------------------------------------------------------------- 4. риски в Redis

def load_risks(bureau_api, redis_client):
    # HSET перезаписывает поле с тем же именем, поэтому при повторном запуске дублей не будет
    regions = bureau_api.get("/v1/regions")
    region_risks = {r["region_code"]: r["risk_score"] for r in regions}
    if region_risks:
        redis_client.hset(REDIS_REGION_KEY, mapping=region_risks)

    merchants_count = 0
    cursor = None
    while True:
        params = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        data = bureau_api.get("/v1/merchants/risk", params)
        merchant_risks = {m["merchant_id"]: m["risk_score"] for m in data["items"]}
        if merchant_risks:
            redis_client.hset(REDIS_MERCHANT_KEY, mapping=merchant_risks)
        merchants_count += len(merchant_risks)
        cursor = data["nextCursor"]
        if not cursor:
            break
    log.info("риски в Redis: регионов %d, мерчантов %d", len(region_risks), merchants_count)
