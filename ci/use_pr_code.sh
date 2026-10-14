#!/usr/bin/env bash
# Подставляет rest-api/ и grpc/ из PR (лежит в .pr/) в рабочую копию базовой ветки.
# Всё остальное (ci/, .github/) остаётся из базовой ветки, поэтому PR не может
# поменять ни тесты, ни workflow. Код студента дальше запускается только в Docker.
set -euo pipefail

PR_DIR="${1:-.pr}"

fail() { echo "::error::$*" >&2; exit 1; }

# Симлинки могли бы указывать на файлы раннера вне папок студента.
links="$(find "$PR_DIR/rest-api" "$PR_DIR/grpc" -type l 2>/dev/null || true)"
if [ -n "$links" ]; then
  fail "В PR есть символические ссылки, уберите их: ${links//$PR_DIR\//}"
fi

for dir in rest-api grpc; do
  rm -rf "$dir"
  if [ -d "$PR_DIR/$dir" ]; then
    cp -R "$PR_DIR/$dir" "$dir"
  fi
done
rm -rf "$PR_DIR"
