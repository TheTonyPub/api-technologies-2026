#!/usr/bin/env bash
# Собирает grpc/ в контейнер, запускает python server.py и прогоняет тесты.
# Локально: pip install -r ci/requirements.txt && bash ci/run_grpc.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/grpc"
IMAGE="homework-grpc:ci"
CONTAINER="homework-grpc"
PORT="${GRPC_PORT:-50051}"

fail() { echo "::error::$*" >&2; exit 1; }

if [ ! -d "$SERVICE_DIR" ]; then
  echo "Папки grpc/ нет — проверка gRPC пропущена"
  exit 0
fi
[ -f "$SERVICE_DIR/server.py" ] || fail "Нет файла grpc/server.py"
[ -f "$SERVICE_DIR/requirements.txt" ] || fail "Нет файла grpc/requirements.txt"


cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "::group::Сборка образа"
docker build -t "$IMAGE" -f "$ROOT/ci/docker/grpc.Dockerfile" "$SERVICE_DIR"
docker image ls "$IMAGE" --format 'Размер образа: {{.Size}}'
echo "::endgroup::"

echo "::group::Запуск python server.py"
docker run -d --name "$CONTAINER" -p "$PORT:50051" "$IMAGE" python server.py >/dev/null
sleep 2
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
  docker logs "$CONTAINER" || true
  fail "Сервер завершился сразу после запуска"
fi
echo "::endgroup::"

status=0
GRPC_TARGET="localhost:$PORT" GRPC_DIR="$SERVICE_DIR" \
  pytest "$ROOT/ci/grpc_tests" -v -s -p no:cacheprovider --tb=short --color=yes || status=$?

echo "::group::Логи сервиса"
docker logs "$CONTAINER" 2>&1 | tail -n 200 || true
echo "::endgroup::"
exit "$status"
