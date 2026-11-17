.PHONY: up reset logs db smoke test proto local-env

up:
	docker compose up --build

reset:
	docker compose down -v && docker compose up --build

logs:
	docker compose logs -f --tail=100

db:
	docker compose up -d postgres redis

smoke:
	bash scripts/smoke.sh

test:
	python scripts/dev.py test

proto:
	python scripts/dev.py proto

local-env:
	python scripts/dev.py local-env
