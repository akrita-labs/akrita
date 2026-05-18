# AKRITA — common development tasks.
# Run `make help` to see the targets.

.PHONY: help install test run stop logs demo fmt lint contracts-build contracts-test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: ## Install Python deps for local (non-Docker) development
	pip install -e ".[dev]"

test: ## Run the full Python test suite
	MOCK_MODE=1 python -m pytest orchestrator/tests/ -v

run: ## Bring up the orchestrator + 3 agents in Docker (MOCK_MODE)
	docker compose up --build

run-detached: ## Bring up the stack in the background
	docker compose up --build -d

stop: ## Stop the stack
	docker compose down

logs: ## Tail combined service logs
	docker compose logs -f

demo: ## Trigger the canonical 30-second demo flow against a running stack
	@curl -sS -X POST http://localhost:8000/demo/run | python -m json.tool

state: ## Print current keeper state (balances, fills, inventory)
	@echo "=== Balances ==="
	@curl -sS http://localhost:8000/state/balances | python -m json.tool
	@echo "=== Fills ==="
	@curl -sS http://localhost:8000/state/fills | python -m json.tool

fmt: ## Format Python with ruff
	ruff format shared adapters orchestrator agents

lint: ## Lint Python with ruff
	ruff check shared adapters orchestrator agents

contracts-build: ## Compile Solidity contracts with forge
	cd contracts && forge build

contracts-test: ## Run Foundry tests
	cd contracts && forge test -vv

contracts-deploy: ## Deploy contracts to Arc testnet (requires PRIVATE_KEY env)
	cd contracts && forge script script/Deploy.s.sol --rpc-url $$ARC_RPC_URL --broadcast

clean: ## Remove Python + Docker artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	docker compose down -v 2>/dev/null || true
