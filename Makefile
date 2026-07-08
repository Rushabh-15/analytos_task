# Analytos Brain — operator surface. `make help` lists everything.
SHELL := /bin/bash
FILES ?= seed-data/*.md
RUN   ?= $(shell date +%Y%m%d-%H%M%S)

.PHONY: help bootstrap serve app ingest ingest-fixture verify agents blog brief ask-content ask-gtm negative-demo policy-test compose-up compose-down clean

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

bootstrap: ## install omnigraph + python deps, create .env
	scripts/bootstrap.sh

serve: ## apply cluster and serve omnigraph locally (foreground)
	scripts/serve_local.sh

app: ## run the review console on :8000 (foreground)
	@set -a && . ./.env && set +a && \
	OMNIGRAPH_TOKEN_REVIEWER=$$TOK_REVIEWER uvicorn app.main:app --host 127.0.0.1 --port 8000

ingest: ## ingest FILES with the configured LLM → review branch
	@set -a && . ./.env && set +a && python3 -m pipeline.ingest $(FILES) --run-id $(RUN)

ingest-fixture: ## deterministic keyless ingest (fixtures + mock embeddings)
	@set -a && . ./.env && set +a && \
	EXTRACT_PROVIDER=fixture OMNIGRAPH_EMBED_PROVIDER=mock \
	python3 -m pipeline.ingest $(FILES) --run-id $(RUN) --force

verify: ## full e2e verification incl. Cedar negative tests (server must be up)
	scripts/verify_e2e.sh

blog: ## content agent writes a blog (PRODUCT=prod-stockly TOPIC="…")
	@set -a && . ./.env && set +a && \
	python3 -m agents.content_agent --product $(or $(PRODUCT),prod-stockly) --topic "$(or $(TOPIC),proof over promises)"

brief: ## gtm agent writes prospecting brief(s) (SEGMENT=… optional)
	@set -a && . ./.env && set +a && \
	python3 -m agents.gtm_agent $(if $(SEGMENT),--segment $(SEGMENT),)

ask-content: ## Q&A via content agent (Q="…")
	@set -a && . ./.env && set +a && python3 -m agents.content_agent --ask "$(Q)"

ask-gtm: ## Q&A via gtm agent (Q="…")
	@set -a && . ./.env && set +a && python3 -m agents.gtm_agent --ask "$(Q)"

negative-demo: ## prove act-content is 403'd from the comms graph via MCP
	@set -a && . ./.env && set +a && python3 -m agents.negative_demo

policy-test: ## run declarative Cedar test suites
	omnigraph policy test --tests cluster/policies/knowledge.tests.yaml --cluster cluster
	omnigraph policy test --tests cluster/policies/comms.tests.yaml --cluster cluster

compose-up: ## hosted stack via docker compose
	docker compose --env-file .env -f deploy/docker-compose.yml up --build -d

compose-down: ## stop the hosted stack
	docker compose --env-file .env -f deploy/docker-compose.yml down

clean: ## remove run artifacts
	rm -rf out/
