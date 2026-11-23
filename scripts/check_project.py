#!/usr/bin/env python3
"""Проверка локального стенда ДЗ 4. Для HTTP достаточно стандартной библиотеки."""

import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from dev import PORTS, ROOT, read_env


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTP = build_opener(ProxyHandler({}), NoRedirect())
LOG = logging.getLogger("check_project")


def address(port):
    return f"http://127.0.0.1:{port}"


class Report:
    def __init__(self, timeout, compose_timeout):
        self.timeout = timeout
        self.compose_timeout = compose_timeout
        self.counts = Counter()

    def record(self, status, name, detail=""):
        self.counts[status] += 1
        level = logging.ERROR if status == "FAIL" else logging.INFO
        LOG.log(level, "[%s] %s %s", status, name, detail)

    def expect(self, name, condition, detail=""):
        self.record("OK" if condition else "FAIL", name, detail)

    def http(self, name, url, *, status=200, method="GET", token=None, timeout=None,
             validate=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = Request(url, headers=headers, method=method)
        started = time.monotonic()
        try:
            try:
                response = HTTP.open(request, timeout=timeout or self.timeout)
            except HTTPError as exc:
                response = exc
            with response:
                text = response.read().decode("utf-8", errors="replace")
                actual = response.status
                response_headers = response.headers
        except (OSError, HTTPException) as exc:
            self.record("FAIL", name, f"{method} {url} ({time.monotonic() - started:.3f} с) {exc}")
            return None

        try:
            body = json.loads(text)
        except ValueError:
            body = None
        elapsed = time.monotonic() - started
        LOG.debug("%s %s -> %s (%.3f с) headers=%s body=%s",
                  method, url, actual, elapsed, dict(response_headers), text)
        valid = actual == status and isinstance(body, dict)
        if valid and validate is not None:
            valid = validate(body, response_headers)
        meta = " ".join(f"{key}={response_headers[key]}" for key in ("X-Cache", "X-Request-Id")
                        if key in response_headers)
        detail = f"{method} {url} -> {actual} ({elapsed:.3f} с) {meta}".rstrip()
        if not valid:
            detail += f" | ожидался HTTP {status} и ответ по контракту | {text[:500]}"
        self.expect(name, valid, detail)
        return body if valid else None

    def compose(self, name, service, *command, validate=lambda stdout: True):
        started = time.monotonic()
        try:
            result = subprocess.run(
                ["docker", "compose", "exec", "-T", service, *command],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.compose_timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.record("FAIL", name, f"{service} ({time.monotonic() - started:.3f} с) {exc}")
            return
        elapsed = time.monotonic() - started
        stdout = result.stdout.strip()
        LOG.debug("Compose %s (%.3f с) stdout=%s stderr=%s", service, elapsed, stdout, result.stderr)
        valid = result.returncode == 0 and validate(stdout)
        output = stdout if valid else (result.stderr.strip() or stdout)
        self.expect(name, valid, f"{service} exit={result.returncode} ({elapsed:.3f} с) {output[:500]}")


def sync_and_wait(report, enrichment, timeout):
    sync = report.http("Loader sync", f"{address(PORTS['loader'])}/sync", method="POST",
                       timeout=timeout, validate=lambda body, _: bool(body.get("last_sync_at")))
    if sync is None:
        return enrichment
    marker = sync["last_sync_at"]
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            report.record("FAIL", "Enrichment после sync", f"витрина не догнала {marker} за {timeout:g} с")
            return enrichment
        status = report.http("Enrichment после sync", f"{address(PORTS['enrichment'])}/status",
                             timeout=min(report.timeout, remaining))
        if status is None:
            return enrichment
        try:
            caught_up = datetime.fromisoformat(status["last_sync_at"]) >= datetime.fromisoformat(marker)
        except (KeyError, TypeError, ValueError):
            caught_up = False
        if status.get("ready") is True and caught_up:
            report.record("OK", "Витрина после sync", f"last_sync_at={status['last_sync_at']}")
            return status
        time.sleep(max(0, min(2, deadline - time.monotonic())))


def check_data(report, args):
    loader = report.http("Loader status", f"{address(PORTS['loader'])}/status")
    enrichment = report.http("Enrichment status", f"{address(PORTS['enrichment'])}/status")
    if loader is not None:
        report.expect("Loader готов", loader.get("initial_done") is True
                      and not loader.get("dry_run") and not loader.get("last_error"),
                      f"initial_done={loader.get('initial_done')} companies={loader.get('companies')} "
                      f"versions={loader.get('versions')} groups={loader.get('groups')}")
    if args.sync:
        if loader and loader.get("initial_done") is True and not loader.get("dry_run"):
            enrichment = sync_and_wait(report, enrichment, args.sync_timeout)
        else:
            report.record("FAIL", "Loader sync", "нужна завершённая первичная загрузка в PostgreSQL")
    if enrichment is not None:
        report.expect("Enrichment готов", enrichment.get("ready") is True and not enrichment.get("last_error"),
                      f"ready={enrichment.get('ready')} companies={enrichment.get('companies')} "
                      f"bank_clients={enrichment.get('bank_clients')} redis_keys={enrichment.get('redis_keys')}")
    history_inn = args.history_inn or args.inn
    history = f"{address(PORTS['enrichment'])}/v1/internal/companies/{history_inn}/history"
    report.http("История SCD2", history, validate=lambda body, _: body.get("inn") == history_inn
                and isinstance(body.get("versions"), list) and len(body["versions"]) > 0
                and body.get("versionsCount") == len(body["versions"]))


def check_api(report, args, token):
    gateway = f"{address(PORTS['gateway'])}/v1/companies"
    group_inn = args.group_inn or args.inn
    group = f"{group_inn}/group"

    def card(body, _):
        return body.get("inn") == args.inn and isinstance(body.get("shortName"), str)

    def group_schema(body, _):
        members = body.get("members")
        return (body.get("inn") == group_inn and isinstance(members, list)
                and body.get("totalMembers") == len(members)
                and all(isinstance(member, dict) for member in members))

    def scoring(body, _):
        probability = body.get("probability")
        return (body.get("inn") == args.inn and type(probability) in (int, float)
                and 0 <= probability <= 1 and bool(body.get("modelVersion")))

    report.http("Client Info карточка", f"{address(PORTS['client-info'])}/v1/companies/{args.inn}", validate=card)
    report.http("Group Companies группа", f"{address(PORTS['group-companies'])}/v1/companies/{group}",
                validate=group_schema)
    report.http("Scoring прогноз", f"{address(PORTS['scoring'])}/v1/companies/{args.inn}/scoring",
                validate=scoring)

    report.http("Gateway без токена", f"{gateway}/{args.inn}", status=401,
                validate=lambda body, _: body.get("code") == "UNAUTHORIZED")
    report.http("Gateway неверный формат ИНН", f"{gateway}/abc", token=token, status=400,
                validate=lambda body, _: body.get("code") == "INVALID_REQUEST")
    report.http("Gateway неизвестный ИНН", f"{gateway}/0000000000", token=token, status=404,
                validate=lambda body, _: body.get("code") == "COMPANY_NOT_FOUND")
    report.http("Gateway карточка", f"{gateway}/{args.inn}", token=token, validate=card)
    report.http("Gateway повтор карточки", f"{gateway}/{args.inn}", token=token,
                validate=lambda body, headers: card(body, headers) and headers.get("X-Cache") == "HIT")
    full = report.http("Gateway группа", f"{gateway}/{group}", token=token, validate=group_schema)
    filtered = report.http("Gateway группа только с клиентами банка", f"{gateway}/{group}?onlyBankClients=true",
                           token=token, validate=group_schema)
    if full is not None and filtered is not None:
        expected = [member for member in full["members"] if member.get("isBankClient") is True]
        report.expect("Фильтр группы", filtered["members"] == expected,
                      f"все={len(full['members'])} клиенты банка={len(filtered['members'])}")
    report.http("Gateway скоринг", f"{gateway}/{args.inn}/scoring", token=token, validate=scoring)


def check_infrastructure(report):
    report.compose("PostgreSQL схема и outbox", "postgres", "sh", "-ec",
                   "psql -X -v ON_ERROR_STOP=1 -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" "
                   "-c 'SELECT count(*) AS snapshot_rows FROM company_snapshot' "
                   "-c 'SELECT count(*) AS pending_events FROM company_outbox WHERE published_at IS NULL'")
    report.compose("Redis PING", "redis", "redis-cli", "ping", validate=lambda text: text == "PONG")
    report.compose("Kafka топики", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server",
                   "kafka:9092", "--list", validate=lambda text: {"company.changes", "company.audit"}
                   <= set(text.splitlines()))
    report.compose("Publisher healthcheck", "event-publisher", "/publisher", "-healthcheck")
    report.compose("ML Model gRPC GetInfo", "ml-model", "python", "-c",
                   "import grpc, scoring_pb2 as pb, scoring_pb2_grpc as rpc; "
                   "info = rpc.CompanyScoringStub(grpc.insecure_channel('localhost:50051'))"
                   ".GetInfo(pb.InfoRequest(), timeout=3); "
                   "print(info); assert info.features and info.model_version")


def check_monitoring(report):
    def loader_target_up(body, _):
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("activeTargets"), list):
            return False
        return any(isinstance(target, dict) and target.get("health") == "up"
                   and isinstance(target.get("labels"), dict) and target["labels"].get("job") == "loader"
                   for target in data["activeTargets"])

    report.http("Prometheus Loader target", f"{address(9090)}/api/v1/targets", validate=loader_target_up)
    report.http("Grafana health", f"{address(3000)}/api/health",
                validate=lambda body, _: body.get("database") == "ok")


def parse_inn(value):
    if re.fullmatch(r"[0-9]{10}", value) is None:
        raise argparse.ArgumentTypeError("ИНН юрлица должен состоять из 10 цифр")
    return value


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("укажи положительное время в секундах")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inn", type=parse_inn, default="0201141964", help="ИНН для карточки и скоринга")
    parser.add_argument("--group-inn", type=parse_inn, help="ИНН компании для проверки группы")
    parser.add_argument("--history-inn", type=parse_inn, help="ИНН для проверки истории SCD2")
    parser.add_argument("--log", type=Path, default=ROOT / "project-check.log", help="путь к файлу лога")
    parser.add_argument("--timeout", type=positive_seconds, default=3, help="таймаут HTTP, с")
    parser.add_argument("--compose-timeout", type=positive_seconds, default=15, help="таймаут команды Docker, с")
    parser.add_argument("--sync", action="store_true", help="вызвать Loader POST /sync и дождаться витрины")
    parser.add_argument("--sync-timeout", type=positive_seconds, default=180, help="таймаут каждой фазы sync, с")
    parser.add_argument("--http-only", action="store_true", help="пропустить проверки через Docker Compose")
    parser.add_argument("--monitoring", action="store_true", help="проверить Prometheus и Grafana")
    args = parser.parse_args()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    try:
        file = logging.FileHandler(args.log, encoding="utf-8")
    except OSError as exc:
        parser.error(f"не удалось открыть лог {args.log}: {exc}")
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file], format="%(asctime)s %(levelname)s %(message)s")

    env_file = ROOT / ".env"
    token = os.getenv("GATEWAY_TOKEN")
    if token is None:
        token = read_env(env_file).get("GATEWAY_TOKEN", "change-me") if env_file.exists() else "change-me"
    LOG.info("Локальная проверка | ИНН=%s | лог=%s", args.inn, args.log.resolve())
    report = Report(args.timeout, args.compose_timeout)
    for service, port in PORTS.items():
        report.http(f"{service} health", f"{address(port)}/health",
                    validate=lambda body, _: body.get("status") == "ok")
    check_data(report, args)
    check_api(report, args, token)
    if args.http_only:
        report.record("SKIP", "Инфраструктура", "режим --http-only")
    else:
        check_infrastructure(report)
    if args.monitoring:
        check_monitoring(report)
    LOG.info("Итог | OK=%d FAIL=%d SKIP=%d", report.counts["OK"], report.counts["FAIL"], report.counts["SKIP"])
    return int(report.counts["FAIL"] > 0)


if __name__ == "__main__":
    sys.exit(main())
