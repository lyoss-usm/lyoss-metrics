.DEFAULT_GOAL := help
SHELL := /bin/bash

# PROJECT_ID: el de PROYECTO en .env; si no existe, el proyecto activo de gcloud.
# Se puede forzar: make db-test PROJECT_ID=mi-proyecto
PROJECT_ID ?= $(shell sed -n 's/^PROYECTO=//p' .env 2>/dev/null | tr -d "'\"" | head -n1)
ifeq ($(PROJECT_ID),)
PROJECT_ID := $(shell gcloud config get-value project 2>/dev/null)
endif
export PROJECT_ID

.PHONY: help install lock auth check-project db-raw db-test db-test-reset run-task test audit clean

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Crea .venv y sincroniza dependencias con uv.lock
	uv sync

lock: ## Regenera uv.lock tras cambiar pyproject.toml
	uv lock

auth: ## Login de Application Default Credentials (una vez por maquina)
	gcloud auth application-default login

check-project:
	@test -n "$(PROJECT_ID)" || { echo "PROJECT_ID vacio: define PROYECTO en .env o usa PROJECT_ID=..."; exit 1; }

db-raw: check-project ## Crea el dataset raw y sus 12 tablas (PRODUCCION)
	./infra/01_create_raw.sh

db-test: check-project ## Crea el dataset raw_test y sus 12 tablas
	./infra/02_create_raw_test.sh

db-test-reset: check-project ## Borra y recrea raw_test desde cero
	RESET=1 ./infra/02_create_raw_test.sh

run-task: ## Ejecuta una tarea: make run-task TASK=users [REPO_ID=123]
	@test -n "$(TASK)" || { echo "Uso: make run-task TASK=<tarea> [REPO_ID=N]"; exit 1; }
	uv run python -m collector.main --task $(TASK) $(if $(REPO_ID),--repo-id $(REPO_ID))

test: ## Ejecuta los tests unitarios (pytest, sin red ni credenciales)
	uv run pytest

audit: ## Audita los endpoints de GitHub (usa GH_TOKEN de .env)
	uv run python api_audit.py

clean: ## Elimina .venv y caches de Python
	rm -rf .venv
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
