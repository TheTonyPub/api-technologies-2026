#!/usr/bin/env bash
# Собирает rest-api/ в контейнер, запускает через uvicorn и прогоняет тесты.
# Локально: pip install -r ci/requirements.txt && bash ci/run_rest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/rest-api"
IMAGE="homework-rest:ci"
CONTAINER="homework-rest"
PORT="${REST_PORT:-8000}"

fail() { echo "::error::$*" >&2; exit 1; }

[ -d "$SERVICE_DIR" ] || fail "Нет папки rest-api/ в корне репозитория"
[ -f "$SERVICE_DIR/main.py" ] || fail "Нет файла rest-api/main.py"
[ -f "$SERVICE_DIR/requirements.txt" ] || fail "Нет файла rest-api/requirements.txt"


cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "::group::Сборка образа"
docker build -t "$IMAGE" -f "$ROOT/ci/docker/rest.Dockerfile" "$SERVICE_DIR"
docker image ls "$IMAGE" --format 'Размер образа: {{.Size}}'
echo "::endgroup::"

echo "::group::Запуск uvicorn main:app"
docker run -d --name "$CONTAINER" -p "$PORT:8000" "$IMAGE" \
  uvicorn main:app --host 0.0.0.0 --port 8000 >/dev/null
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/openapi.json" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
    break
  fi
  sleep 1
done
if [ -z "${ready:-}" ]; then
  docker logs "$CONTAINER" || true
  fail "Сервис не запустился: uvicorn main:app не отдаёт /openapi.json на порту 8000"
fi
echo "Сервис запущен"
echo "::endgroup::"

status=0
REST_BASE_URL="http://localhost:$PORT" REST_DIR="$SERVICE_DIR" \
  pytest "$ROOT/ci/rest_tests" -v -p no:cacheprovider --tb=short --color=yes || status=$?

echo "::group::Логи сервиса"
docker logs "$CONTAINER" 2>&1 | tail -n 200 || true
echo "::endgroup::"
exit "$status"
