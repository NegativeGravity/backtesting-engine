.PHONY: install test coverage lint format format-check typecheck frontend-install frontend-check quality schemas schema-check validate-examples import-data broker-smoke strategy-smoke replay-build analytics-report engine dashboard

install:
	uv sync --all-groups
	npm ci --prefix apps/dashboard_web

test:
	uv run pytest

coverage:
	uv run pytest --cov=vex_contracts --cov=vex_data_engine --cov=vex_broker --cov=vex_strategy --cov=vex_replay --cov=vex_analytics --cov-report=term-missing --cov-report=xml

lint:
	uv run ruff check src tests scripts

format:
	uv run ruff format src tests scripts

format-check:
	uv run ruff format --check src tests scripts

typecheck:
	uv run pyright

frontend-install:
	npm ci --prefix apps/dashboard_web

frontend-check:
	npm run check --prefix apps/dashboard_web

schemas:
	uv run vex-contracts export-schemas --output schemas

schema-check:
	uv run python scripts/check_schema_drift.py

validate-examples:
	uv run vex-contracts validate --kind dataset-manifest --path examples/configs/dataset.yaml
	uv run vex-contracts validate --kind data-engine-config --path examples/configs/data_engine.yaml
	uv run vex-contracts validate --kind symbol-profile --path examples/configs/symbol_xauusd.yaml
	uv run vex-contracts validate --kind strategy-descriptor --path examples/configs/strategy.yaml
	uv run vex-contracts validate --kind run-config --path examples/configs/run.yaml
	uv run vex-contracts validate --kind strategy-runtime-config --path examples/configs/strategy_runtime.yaml
	uv run vex-contracts validate --kind analytics-config --path examples/configs/analytics.yaml
	uv run vex-contracts validate --kind strategy-descriptor --path examples/configs/strategy_sdk_smoke.yaml
	uv run vex-contracts validate --kind run-config --path examples/configs/run_strategy_smoke.yaml
	uv run vex-contracts validate --kind strategy-package-manifest --path strategies/sma_cross_demo/package.yaml

import-data:
	uv run vex-data import --project-root . --manifest examples/configs/dataset.yaml --symbol-profile examples/configs/symbol_xauusd.yaml --config examples/configs/data_engine.yaml

broker-smoke:
	uv run vex-broker smoke --project-root .

strategy-smoke:
	uv run vex-strategy run --project-root .

replay-build:
	uv run vex-replay build --project-root . --max-close-batches 250

analytics-report:
	uv run vex-analytics report --project-root . --run-id run_xauusd_sdk_smoke_v1 --output data/replay/analytics-cli-report.json

engine:
	uv run vex-engine --project-root . --host 127.0.0.1 --port 8001

dashboard:
	uv run vex-dashboard --project-root . --engine-url http://127.0.0.1:8001 --host 127.0.0.1 --port 8000

quality: lint format-check typecheck test validate-examples schema-check frontend-check
