COMPOSE ?= docker compose

-include .env

LOCAL_DB ?= 1
LOCAL_OLLAMA ?= 1
LOCAL_BACKEND ?= 1

PROFILES :=

ifeq ($(LOCAL_BACKEND),1)
PROFILES += --profile local-backend --profile local-db --profile local-ollama
endif

ifeq ($(LOCAL_DB),1)
PROFILES += --profile local-db
endif

ifeq ($(LOCAL_OLLAMA),1)
PROFILES += --profile local-ollama
endif

DATA_DIR := $(MEMORY_DATA_DIR)
INGEST_DIR := $(MEMORY_INGEST_DIR)
OBSIDIAN_DIR := $(MEMORY_OBSIDIAN_DIR)
DEFAULTS_DIR := $(CURDIR)/defaults
MEMORY_NETWORK ?= $(if $(MEMORY_NETWORK_NAME),$(MEMORY_NETWORK_NAME),memory-internal)

.PHONY: init up down logs ps rebuild

init:
	@test -n "$(DATA_DIR)" || { echo "Set MEMORY_DATA_DIR in .env"; exit 1; }
	@test -n "$(INGEST_DIR)" || { echo "Set MEMORY_INGEST_DIR in .env"; exit 1; }
	@test -n "$(OBSIDIAN_DIR)" || { echo "Set MEMORY_OBSIDIAN_DIR in .env"; exit 1; }
	@docker network inspect "$(MEMORY_NETWORK)" >/dev/null 2>&1 || docker network create "$(MEMORY_NETWORK)" >/dev/null
	@mkdir -p \
		"$(DATA_DIR)/settings" \
		"$(DATA_DIR)/status" \
		"$(DATA_DIR)/backups" \
		"$(DATA_DIR)/docs-worker" \
		"$(DATA_DIR)/email-worker" \
		"$(DATA_DIR)/obsidian-worker" \
		"$(DATA_DIR)/github-worker" \
		"$(DATA_DIR)/enricher-worker" \
		"$(DATA_DIR)/postgres" \
		"$(DATA_DIR)/ollama" \
		"$(INGEST_DIR)/gdrive" \
		"$(INGEST_DIR)/docs" \
		"$(OBSIDIAN_DIR)"
	@for file in documents email obsidian github enrichment secrets; do \
		src="$(DEFAULTS_DIR)/settings/$$file.json"; \
		dst="$(DATA_DIR)/settings/$$file.json"; \
		if [ ! -e "$$dst" ]; then cp "$$src" "$$dst"; fi; \
	done
	@if [ ! -e "$(DATA_DIR)/email-worker/accounts.json" ]; then \
		cp "$(DEFAULTS_DIR)/email-worker/accounts.json" "$(DATA_DIR)/email-worker/accounts.json"; \
	fi

up: init
	$(COMPOSE) $(PROFILES) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

rebuild:
	$(COMPOSE) $(PROFILES) build --no-cache
