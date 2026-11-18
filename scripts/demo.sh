#!/usr/bin/env bash
# Единая точка входа сценария проверки. Только публичные API наших сервисов (Gateway, /status, /sync).
# Печатает каждый вызов и ответ, итоги пишет в demo-result.json.
#
#   bash scripts/demo.sh
#   DEMO_HISTORY_INN=7700000001 DEMO_SCORING_INNS="7700000001 7700000002 7700000003" bash scripts/demo.sh
set -euo pipefail
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
  curl -fsS --max-time 10 -H "Authorization: Bearer $TOKEN" "$1" | tee /dev/stderr
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
curl -fsS --max-time 5 "$LOADER/status" > "$TMP/loader.json"
wait_enrichment "$(jget "$TMP/loader.json" 'd["last_sync_at"]')"
cat "$TMP/loader.json" "$TMP/enrich.json"
echo

echo "=== 2. Инкремент: POST /sync"
curl -fsS --max-time "${DEMO_SYNC_TIMEOUT_SEC:-180}" -X POST "$LOADER/sync" > "$TMP/sync.json"
cat "$TMP/sync.json"
echo
wait_enrichment "$(jget "$TMP/sync.json" 'd["last_sync_at"]')"
curl -fsS --max-time 5 "$LOADER/status" > "$TMP/loader2.json"

echo "=== 3. История компании"
HISTORY_INN=${DEMO_HISTORY_INN:-$(jget "$TMP/loader2.json" '(d.get("changed_inns") or [None])[0]')}
if [ -n "$HISTORY_INN" ]; then
  call "$ENRICH/v1/internal/companies/$HISTORY_INN/history" > "$TMP/history.json"
else
  echo "нет компаний с изменениями, историю не показываем"; echo 'null' > "$TMP/history.json"
fi

echo "=== 4. Карточка компании"
CARD_INN=${DEMO_COMPANY_INN:-$HISTORY_INN}
if [ -n "$CARD_INN" ]; then
  call "$GW/v1/companies/$CARD_INN"
  curl -fsS --max-time 10 -D "$TMP/card.headers" -H "Authorization: Bearer $TOKEN" \
    "$GW/v1/companies/$CARD_INN" > "$TMP/card.json"
  grep -Eiq '^X-Cache: *HIT([[:space:]]|$)' "$TMP/card.headers"
else
  echo "Для проверки карточки задай DEMO_COMPANY_INN"
fi
UNKNOWN_INN=${DEMO_UNKNOWN_INN:-0000000000}
UNKNOWN_STATUS=$(curl -sS --max-time 10 -o "$TMP/unknown.json" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "$GW/v1/companies/$UNKNOWN_INN")
test "$UNKNOWN_STATUS" = 404
test "$(jget "$TMP/unknown.json" 'd["code"]')" = COMPANY_NOT_FOUND

echo "=== 5. Группа компаний"
GROUP_INN=${DEMO_GROUP_INN:-$CARD_INN}
if [ -n "$GROUP_INN" ]; then
  call "$GW/v1/companies/$GROUP_INN/group"
  call "$GW/v1/companies/$GROUP_INN/group?onlyBankClients=true"
else
  echo "Для проверки группы задай DEMO_GROUP_INN"
fi

echo "=== 6. Скоринг трёх ИНН (шаг Фёдора)"
SCORING_INNS=${DEMO_SCORING_INNS:-$(jget "$TMP/loader2.json" '" ".join((d.get("changed_inns") or [])[:3])')}
echo '{}' > "$TMP/scores.json"
for inn in $SCORING_INNS; do
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
"$PY" - "$TMP" "$OUT" "$HISTORY_INN" <<'EOF'
import json, sys
tmp, out, history_inn = sys.argv[1], sys.argv[2], sys.argv[3]
load = lambda name: json.load(open(f"{tmp}/{name}"))
loader, loader2, enrich, sync = load("loader.json"), load("loader2.json"), load("enrich.json"), load("sync.json")

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
    "lastSyncAt": loader2.get("last_sync_at"),
    "history": {"inn": history_inn or None, "versions": load("history.json")},
    "scores": load("scores.json"),
}
json.dump(result, open(out, "w"), ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
EOF
