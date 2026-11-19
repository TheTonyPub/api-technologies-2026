#!/usr/bin/env bash
# Единая точка входа сценария проверки. Только публичные API наших сервисов (Gateway, /status, /sync).
# Печатает каждый вызов и ответ, итоги пишет в demo-result.json.
#
#   ./scripts/demo.sh
#   DEMO_HISTORY_INN=7700000001 DEMO_SCORING_INNS="7700000001 7700000002 7700000003" bash scripts/demo.sh
set -euo pipefail
ACCEPTANCE=0
case "${1:-}" in
  --acceptance)
    ACCEPTANCE=1
    if [[ -n "${DEMO_EXPECTED_SPARK:-}" ]]; then
      if [[ ! -r "$DEMO_EXPECTED_SPARK" ]]; then
        echo "Не удалось открыть DEMO_EXPECTED_SPARK" >&2
        exit 2
      fi
    elif [[ ! "${DEMO_EXPECTED_NEW_VERSIONS:-}" =~ ^(0|[1-9][0-9]*)$ || ! -r "${DEMO_EXPECTED_HISTORY:-}" ]]; then
      echo "Задай DEMO_EXPECTED_SPARK или DEMO_EXPECTED_NEW_VERSIONS вместе с DEMO_EXPECTED_HISTORY" >&2
      exit 2
    fi
    ;;
  "") ;;
  *) echo "Использование: ./scripts/demo.sh [--acceptance]" >&2; exit 2 ;;
esac
GW=${GW:-http://localhost:8000}
LOADER=${LOADER:-http://localhost:8003}
ENRICH=${ENRICH:-http://localhost:8001}
TOKEN=${GATEWAY_TOKEN:-change-me}
PY=$(command -v python3 || command -v python)   # JSON разбираем питоном, jq не нужен
OUT=demo-result.json
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

call() {
  echo ">>> GET $1" >&2
  curl --fail-with-body -sS --max-time 10 -H "Authorization: Bearer $TOKEN" "$1" | tee /dev/stderr
}

timed_card() {
  local url=$1 output=$2
  echo ">>> GET $url" >&2
  curl -fsS --max-time 10 -D "$output.headers" -o "$output.json" -w '%{time_total}\n' \
    -H "Authorization: Bearer $TOKEN" "$url" > "$output.seconds"
  cat "$output.json"
  printf '\nВремя ответа: %s с\n' "$(cat "$output.seconds")"
}
# jget FILE ВЫРАЖЕНИЕ: достать поле из JSON, например: jget a.json 'd["companies"]'
jget() { "$PY" -c "import json,sys; d=json.load(open(sys.argv[1])); v=$2; print(json.dumps(v) if isinstance(v,(dict,list)) else ('' if v is None else v))" "$1"; }

wait_initial_load() {   # ждём окончания первичной загрузки (до ~15 минут)
  for _ in $(seq 1 180); do
    curl -fsS --max-time 5 "$LOADER/status" | grep -Eq '"initial_done": ?true' && return 0
    sleep 5
  done
  echo "первичная загрузка не закончилась" >&2; return 1
}

wait_enrichment() {
  local marker=$1
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 5 "$ENRICH/status" > "$TMP/enrich.json" &&
       "$PY" -c 'import json, sys
with open(sys.argv[1]) as f:
    status = json.load(f)
sys.exit(not (status.get("ready") and (status.get("last_sync_at") or "") >= sys.argv[2]))' "$TMP/enrich.json" "$marker"; then
      return 0
    fi
    sleep 2
  done
  echo "Enrichment не обновил витрину до $marker" >&2
  return 1
}

echo "=== 1. Первичная загрузка и счётчики"
wait_initial_load
echo ">>> GET $LOADER/status" >&2
curl -fsS --max-time 5 "$LOADER/status" > "$TMP/loader.json"
wait_enrichment "$(jget "$TMP/loader.json" 'd["last_sync_at"]')"
cat "$TMP/loader.json"
echo
echo ">>> GET $ENRICH/status" >&2
cat "$TMP/enrich.json"
echo

echo "=== 2. Инкремент: POST /sync"
echo ">>> POST $LOADER/sync" >&2
if ! curl --fail-with-body -sS --max-time "${DEMO_SYNC_TIMEOUT_SEC:-180}" -X POST "$LOADER/sync" > "$TMP/sync.json"; then
  cat "$TMP/sync.json" >&2
  exit 1
fi
cat "$TMP/sync.json"
echo
wait_enrichment "$(jget "$TMP/sync.json" 'd["last_sync_at"]')"
call "$LOADER/status" > "$TMP/loader2.json"

echo "=== 3. История компании"
if [ "$ACCEPTANCE" = 1 ]; then
  if [ -n "${DEMO_EXPECTED_SPARK:-}" ]; then
    HISTORY_INN=${DEMO_HISTORY_INN:-$(jget "$DEMO_EXPECTED_SPARK" '(d.get("scd2_demo") or [{}])[0].get("inn")')}
  else
    HISTORY_INN=$(jget "$DEMO_EXPECTED_HISTORY" 'd["inn"]')
  fi
else
  HISTORY_INN=${DEMO_HISTORY_INN:-$(jget "$TMP/loader2.json" '(d.get("changed_inns") or [None])[0]')}
fi
if [ -n "$HISTORY_INN" ]; then
  call "$ENRICH/v1/internal/companies/$HISTORY_INN/history" > "$TMP/history.json"
else
  echo "нет компаний с изменениями, историю не показываем"; echo 'null' > "$TMP/history.json"
fi

echo "=== 4. Карточка компании"
CARD_INN=${DEMO_COMPANY_INN:-$HISTORY_INN}
if [ -n "$CARD_INN" ]; then
  timed_card "$GW/v1/companies/$CARD_INN" "$TMP/card-first"
  timed_card "$GW/v1/companies/$CARD_INN" "$TMP/card-second"
  if grep -Eiq '^X-Cache: *HIT([[:space:]]|$)' "$TMP/card-second.headers"; then
    echo HIT > "$TMP/card.cache"
  fi
else
  echo "Для проверки карточки задай DEMO_COMPANY_INN"
fi
UNKNOWN_INN=${DEMO_UNKNOWN_INN:-0000000000}
echo ">>> GET $GW/v1/companies/$UNKNOWN_INN" >&2
UNKNOWN_STATUS=$(curl -sS --max-time 10 -o "$TMP/unknown.json" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "$GW/v1/companies/$UNKNOWN_INN")
echo "HTTP $UNKNOWN_STATUS"
cat "$TMP/unknown.json"
echo
test "$UNKNOWN_STATUS" = 404
test "$(jget "$TMP/unknown.json" 'd["code"]')" = COMPANY_NOT_FOUND

echo "=== 5. Группа компаний"
GROUP_INN=${DEMO_GROUP_INN:-}
if [ -z "$GROUP_INN" ]; then
  GROUP_CANDIDATES="$(jget "$TMP/loader2.json" '" ".join(d.get("changed_inns") or [])')"
  read -r -a group_candidates <<< "$CARD_INN $GROUP_CANDIDATES"
  for candidate in "${group_candidates[@]}"; do
    call "$GW/v1/companies/$candidate/group" > "$TMP/group-candidate.json"
    if [ -n "$(jget "$TMP/group-candidate.json" 'd.get("groupId")')" ]; then
      GROUP_INN=$candidate
      mv "$TMP/group-candidate.json" "$TMP/group.json"
      break
    fi
  done
else
  call "$GW/v1/companies/$GROUP_INN/group" > "$TMP/group.json"
fi
if [ -n "$GROUP_INN" ]; then
  call "$GW/v1/companies/$GROUP_INN/group?onlyBankClients=true" > "$TMP/bank-group.json"
else
  echo "Для проверки группы задай DEMO_GROUP_INN"
fi

echo "=== 6. Скоринг трёх ИНН (шаг Фёдора)"
SCORING_INNS=${DEMO_SCORING_INNS:-$(jget "$TMP/loader2.json" '" ".join((d.get("changed_inns") or [])[:3])')}
read -r -a score_inns <<< "$SCORING_INNS"
echo '{}' > "$TMP/scores.json"
for inn in "${score_inns[@]}"; do
  call "$GW/v1/companies/$inn/scoring" > "$TMP/score_$inn.json"
  "$PY" - "$TMP/scores.json" "$TMP/score_$inn.json" "$inn" <<'EOF'
import json, sys
scores = json.load(open(sys.argv[1]))
body = json.load(open(sys.argv[2]))
scores[sys.argv[3]] = body["probability"]
json.dump(scores, open(sys.argv[1], "w"))
EOF
done

echo "=== Итог -> $OUT"
"$PY" - "$TMP" "$OUT" "$HISTORY_INN" "$ACCEPTANCE" <<'EOF'
import json, os, sys
from datetime import datetime
from pathlib import Path

tmp, out, history_inn, acceptance = sys.argv[1:]
load = lambda name: json.load(open(f"{tmp}/{name}"))
loader, loader2, enrich, sync = load("loader.json"), load("loader2.json"), load("enrich.json"), load("sync.json")
card_present = Path(tmp, "card-first.json").exists()
card = {
    "body": load("card-second.json"),
    "responseSeconds": [float(Path(tmp, f"card-{attempt}.seconds").read_text())
                        for attempt in ("first", "second")],
    "secondCacheHit": Path(tmp, "card.cache").exists(),
} if card_present else None

def first(d, *names):            # имена полей /status у Enrichment ещё могут поменяться
    return next((d[n] for n in names if n in d), None)

result = {
    "companies": loader2.get("companies"),
    "groups": loader2.get("groups"),
    "bankClients": first(enrich, "bank_clients", "bankClients", "is_bank_client"),
    "snapshotCompanies": first(enrich, "companies", "snapshot_companies"),
    "initialVersions": loader2.get("initial_versions"),
    "versions": loader2.get("versions"),
    "newVersionsAfterIncrement": (loader2.get("versions") or 0) - (loader2.get("initial_versions") or 0),
    "syncCreated": sync.get("created"),
    "initialLoadedAt": loader2.get("initial_loaded_at"),
    "initialLoadSeconds": loader2.get("initial_duration_sec"),
    "syncSince": sync.get("since"),
    "lastSyncAt": loader2.get("last_sync_at"),
    "history": {"inn": history_inn or None, "versions": load("history.json")},
    "companyCard": card,
    "scores": load("scores.json"),
}
summary = json.dumps(result, ensure_ascii=False, indent=2)
Path(out).write_text(summary + "\n", encoding="utf-8")
print(summary)

problems = []
course = os.getenv("DEMO_EXPECTED_SPARK") if acceptance == "1" else None
reference = json.loads(Path(course).read_text(encoding="utf-8-sig")) if course else None
if acceptance == "1":
    expected_companies = int(os.getenv("DEMO_EXPECTED_COMPANIES", "1000"))
    expected_changes = reference["changes_since"]["changes"] if reference else int(os.environ["DEMO_EXPECTED_NEW_VERSIONS"])
    expected = {
        "companies": expected_companies,
        "snapshotCompanies": expected_companies,
        "initialVersions": expected_companies,
        "groups": int(os.getenv("DEMO_EXPECTED_GROUPS", "73")),
        "bankClients": int(os.getenv("DEMO_EXPECTED_BANK_CLIENTS", "451")),
        "newVersionsAfterIncrement": expected_changes,
    }
    problems.extend(f"{key}: ожидалось {value}, получено {result[key]}"
                    for key, value in expected.items() if result[key] != value)
history = result["history"]["versions"]
if not isinstance(history, dict) or history.get("versionsCount", 0) < 2:
    problems.append("нужна история компании с двумя или более версиями")
else:
    versions = history["versions"]
    if [row["isCurrent"] for row in versions] != [False] * (len(versions) - 1) + [True]:
        problems.append("последняя версия должна быть единственной текущей")
    if acceptance == "1":
        def timestamp(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")) if value is not None else None

        actual_intervals = [(timestamp(row["validFrom"]), timestamp(row["validTo"])) for row in versions]
        if reference:
            since = timestamp(reference["changes_since"]["since"])
            if since != timestamp(result["initialLoadedAt"]):
                problems.append("начало окна эталона не совпадает с initial_loaded_at")
            expected = next((row for row in reference["scd2_demo"] if row["inn"] == history["inn"]), None)
            if expected is None:
                problems.append("ИНН отсутствует в scd2_demo эталона")
            else:
                changes = [timestamp(row["ts"]) for row in expected["changes"]]
                actual_changes = [start for start, _ in actual_intervals[1:]]
                actual_closures = [end for _, end in actual_intervals]
                if (len(versions) != expected["versions_since"] or actual_changes != changes
                        or actual_closures != changes + [None] or actual_intervals[0][0] > since):
                    problems.append("интервалы истории не совпадают с эталоном scd2_demo")
        else:
            history_ref = json.loads(Path(os.environ["DEMO_EXPECTED_HISTORY"]).read_text(encoding="utf-8-sig"))
            expected_intervals = [(timestamp(row["valid_from"]), timestamp(row["valid_to"]))
                                  for row in history_ref["versions"]]
            if history["inn"] != history_ref["inn"] or actual_intervals != expected_intervals:
                problems.append("ИНН или интервалы истории не совпадают с эталоном scd2_demo")
if card is None:
    problems.append("не проверена карточка компании")
else:
    if not card["secondCacheHit"]:
        problems.append("второй запрос карточки должен вернуть X-Cache: HIT")
    if any(seconds >= 1 for seconds in card["responseSeconds"]):
        problems.append("оба запроса карточки должны отвечать быстрее 1 секунды")
    if load("card-first.json") != card["body"]:
        problems.append("ответы двух запросов карточки различаются")
if Path(tmp, "group.json").exists():
    group, bank_group = load("group.json"), load("bank-group.json")
    members = group["members"]
    if not members or not group["groupId"] or group["totalMembers"] != len(members):
        problems.append("для приёмки нужна компания из непустой группы (DEMO_GROUP_INN)")
    if (bank_group["members"] != [member for member in members if member["isBankClient"]]
            or bank_group["totalMembers"] != len(bank_group["members"])):
        problems.append("неверный результат фильтра onlyBankClients")
else:
    problems.append("не проверена группа компаний")
scores = result["scores"]
if len(scores) != 3 or any(type(score) not in (int, float) or not 0 <= score <= 1
                           for score in scores.values()):
    problems.append("нужны три разных ИНН с вероятностями от 0 до 1 (DEMO_SCORING_INNS)")
if problems:
    sys.exit("Демо не прошло:\n- " + "\n- ".join(problems))
if acceptance == "1":
    print("Приёмка пройдена")
else:
    print("Демо пройдено")
EOF
