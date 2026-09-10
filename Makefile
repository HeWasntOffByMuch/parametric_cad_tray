# One command to run the whole application locally.
#
#   make dev            API (with its CAD worker pool) + Vite, together
#   make api            just the API
#   make web            just the frontend
#   make test           every suite: core, API, frontend
#   make analytics      the usage report for the local database
#
#   make deploy-local   the production stack in Docker, TLS off, on :8080
#   make deploy-smoke   exercise a running stack the way the browser does
#
PY ?= python3
CORE := packages/tray-core
API := packages/api
WEB := packages/web
export PYTHONPATH := $(CURDIR)/$(CORE):$(CURDIR)/$(API)

API_PORT ?= 8000
WEB_PORT ?= 5173
# The Vite dev server proxies /api, so the browser needs no CORS in development.
export TRAYAPI_ALLOWED_ORIGINS ?= http://localhost:$(WEB_PORT),http://127.0.0.1:$(WEB_PORT)
export TRAYAPI_CACHE_DIR ?= $(CURDIR)/.cache/artifacts
# Usage analytics, local and disposable: .cache/ is gitignored and is a sibling
# of the artifact cache rather than inside it, so sweeping artifacts never
# touches the database. Set it to nothing to develop with analytics off:
#   TRAYMOLD_ANALYTICS_DB= make dev
export TRAYMOLD_ANALYTICS_DB ?= $(CURDIR)/.cache/analytics/analytics.sqlite3

.PHONY: dev api web install test test-core test-api test-web build clean doctor analytics fixtures \
        deploy-local deploy-local-web deploy-smoke deploy-down deploy-logs deploy-check

install:
	$(PY) -m pip install -q cadquery pydantic fastapi uvicorn httpx pytest
	cd $(WEB) && npm install --no-audit --no-fund

## Run the API and the frontend together. Ctrl-C stops both.
dev:
	@mkdir -p $(TRAYAPI_CACHE_DIR)
	@echo "API  http://127.0.0.1:$(API_PORT)   (workers pre-warm, ~4 s)"
	@echo "web  http://127.0.0.1:$(WEB_PORT)"
	@trap 'kill 0' EXIT INT TERM; \
	$(PY) -m uvicorn trayapi.main:app --host 127.0.0.1 --port $(API_PORT) & \
	cd $(WEB) && npm run dev -- --port $(WEB_PORT) --strictPort & \
	wait

api:
	$(PY) -m uvicorn trayapi.main:app --host 127.0.0.1 --port $(API_PORT) --reload

web:
	cd $(WEB) && npm run dev -- --port $(WEB_PORT)

build:
	cd $(WEB) && npm run build

test: test-core test-api test-web

test-core:
	$(PY) -m pytest $(CORE)/tests -q

# Analytics off unless a test turns it on for itself, so a suite run never
# writes into the database `make dev` is filling.
test-api:
	TRAYMOLD_ANALYTICS_DB= $(PY) -m pytest $(API)/tests -q

test-web:
	cd $(WEB) && npm run test

## Rewrite the frontend test fixture from the API. Run after any change to the
## parameter model or the UI hints; `make test-api` checks it is current.
fixtures:
	TRAYMOLD_ANALYTICS_DB= $(PY) tools/dump_fixtures.py

## Read the usage analytics the running API has collected.
analytics:
	@test -n "$(TRAYMOLD_ANALYTICS_DB)" || { echo "TRAYMOLD_ANALYTICS_DB is empty: analytics is disabled."; exit 1; }
	$(PY) -m trayapi.analytics.report --db $(TRAYMOLD_ANALYTICS_DB)

## Print the resolved configuration and check the API answers.
doctor:
	@echo "PYTHONPATH        $(PYTHONPATH)"
	@echo "cache dir         $(TRAYAPI_CACHE_DIR)"
	@echo "allowed origins   $(TRAYAPI_ALLOWED_ORIGINS)"
	@echo "analytics db      $(if $(TRAYMOLD_ANALYTICS_DB),$(TRAYMOLD_ANALYTICS_DB),(disabled))"
	@curl -sf http://127.0.0.1:$(API_PORT)/api/health | head -c 400 || echo "API not running"

clean:
	rm -rf $(WEB)/dist $(WEB)/node_modules/.vite .cache

# -- deployment --------------------------------------------------------------
#
# The same image, compose file and Caddyfile the VPS runs, on your machine. The
# only differences are in deploy/.env.local: no TLS, unprivileged ports, and the
# image built from this checkout rather than pulled from GHCR.
#
# --profile caddy: the local rehearsal always runs the bundled proxy, because
# reproducing the production request path is the point of it.
COMPOSE := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml --env-file deploy/.env.local --profile caddy
LOCAL_URL ?= http://localhost:8080

## Bring the containerised stack up and wait for it to be healthy.
deploy-local:
	@docker version >/dev/null 2>&1 || { echo "The Docker daemon is not reachable. Start Docker Desktop, or the docker service."; exit 1; }
	$(COMPOSE) up -d --build --wait --wait-timeout 300
	@echo
	@echo "API   $(LOCAL_URL)/api/health"
	@echo "next  make deploy-smoke        exercise it"
	@echo "      make deploy-local-web    the UI against it"
	@echo "      make deploy-down         stop and remove"

## Build the frontend the way GitHub Pages will, and serve it against the stack.
deploy-local-web:
	cd $(WEB) && VITE_API_BASE_URL=$(LOCAL_URL) npm run build && npm run preview -- --port 4173 --strictPort

## Every check the deploy workflow runs against production, against a local run.
deploy-smoke:
	./deploy/smoke.sh $(LOCAL_URL)

deploy-logs:
	$(COMPOSE) logs -f --tail=100

deploy-down:
	$(COMPOSE) down

## Everything the deployment can get wrong, without needing a VPS.
deploy-check:
	$(COMPOSE) config -q && echo "compose files parse"
	docker run --rm -v $(CURDIR)/deploy:/etc/caddy:ro \
		-e TRAYMOLD_SITE_ADDRESS=:80 -e TRAYMOLD_TLS_EMAIL=nobody@example.invalid -e TRAYMOLD_MAX_BODY=262144 \
		caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile
