#!/usr/bin/env bash
# Быстрая проверка: отвечают ли сервисы и сколько загрузил Loader.
status=0
for p in 8000 8001 8002 8003 8004 8005; do
  printf 'localhost:%s/health -> ' "$p"
  if ! curl -fsS -m 3 "http://localhost:$p/health"; then
    printf 'DOWN'
    status=1
  fi
  echo
done
echo "loader status:"
curl -fsS -m 3 http://localhost:8003/status || status=1
echo
exit "$status"
