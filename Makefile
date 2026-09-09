# One command to run the whole application locally.
#
#   make dev      API (with its CAD worker pool) + Vite, together
#   make api      just the API
#   make web      just the frontend
#   make test     every suite: core, API, frontend
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

.PHONY: dev api web install test test-core test-api test-web build clean doctor

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

test-api:
	$(PY) -m pytest $(API)/tests -q

test-web:
	cd $(WEB) && npm run test

## Print the resolved configuration and check the API answers.
doctor:
	@echo "PYTHONPATH        $(PYTHONPATH)"
	@echo "cache dir         $(TRAYAPI_CACHE_DIR)"
	@echo "allowed origins   $(TRAYAPI_ALLOWED_ORIGINS)"
	@curl -sf http://127.0.0.1:$(API_PORT)/api/health | head -c 400 || echo "API not running"

clean:
	rm -rf $(WEB)/dist $(WEB)/node_modules/.vite .cache
