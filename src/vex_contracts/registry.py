from typing import Any

from pydantic import TypeAdapter

from vex_contracts.analytics import AnalyticsComparisonReport, AnalyticsConfig, AnalyticsReport
from vex_contracts.broker import BrokerSimulationReport, BrokerStateSnapshot
from vex_contracts.chart import ChartCommand, ChartDrawing
from vex_contracts.data_engine import DataEngineConfig, DataImportReport
from vex_contracts.dataset import DatasetManifest
from vex_contracts.events import EventEnvelope
from vex_contracts.mt5 import (
    Mt5CompatibilityReport,
    Mt5CompatibilitySnapshot,
    Mt5ValidationConfig,
)
from vex_contracts.mt5_bridge import Mt5BridgeConfig
from vex_contracts.orchestration import (
    LiveRunCatalog,
    LiveRunControlCommand,
    LiveRunCreateRequest,
    LiveRunState,
    StrategyPackageManifest,
)
from vex_contracts.orders import OrderRequest
from vex_contracts.replay import (
    ReplayBootstrap,
    ReplayBuildResult,
    ReplayBundleManifest,
    ReplayCatalog,
    ReplayControlCommand,
    ReplayFrame,
)
from vex_contracts.run import BacktestRunConfig
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import (
    StrategyBacktestReport,
    StrategyRuntimeConfig,
)
from vex_contracts.symbol import SymbolProfile

_CONTRACT_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "analytics-config": TypeAdapter(AnalyticsConfig),
    "analytics-report": TypeAdapter(AnalyticsReport),
    "analytics-comparison-report": TypeAdapter(AnalyticsComparisonReport),
    "data-engine-config": TypeAdapter(DataEngineConfig),
    "data-import-report": TypeAdapter(DataImportReport),
    "dataset-manifest": TypeAdapter(DatasetManifest),
    "symbol-profile": TypeAdapter(SymbolProfile),
    "strategy-descriptor": TypeAdapter(StrategyDescriptor),
    "strategy-runtime-config": TypeAdapter(StrategyRuntimeConfig),
    "strategy-backtest-report": TypeAdapter(StrategyBacktestReport),
    "run-config": TypeAdapter(BacktestRunConfig),
    "order-request": TypeAdapter(OrderRequest),
    "strategy-package-manifest": TypeAdapter(StrategyPackageManifest),
    "live-run-create-request": TypeAdapter(LiveRunCreateRequest),
    "live-run-control-command": TypeAdapter(LiveRunControlCommand),
    "live-run-state": TypeAdapter(LiveRunState),
    "live-run-catalog": TypeAdapter(LiveRunCatalog),
    "mt5-bridge-config": TypeAdapter(Mt5BridgeConfig),
    "mt5-compatibility-snapshot": TypeAdapter(Mt5CompatibilitySnapshot),
    "mt5-validation-config": TypeAdapter(Mt5ValidationConfig),
    "mt5-compatibility-report": TypeAdapter(Mt5CompatibilityReport),
    "broker-simulation-report": TypeAdapter(BrokerSimulationReport),
    "broker-state-snapshot": TypeAdapter(BrokerStateSnapshot),
    "chart-command": TypeAdapter(ChartCommand),
    "chart-drawing": TypeAdapter(ChartDrawing),
    "event-envelope": TypeAdapter(EventEnvelope[dict[str, Any]]),
    "replay-bundle-manifest": TypeAdapter(ReplayBundleManifest),
    "replay-catalog": TypeAdapter(ReplayCatalog),
    "replay-bootstrap": TypeAdapter(ReplayBootstrap),
    "replay-frame": TypeAdapter(ReplayFrame),
    "replay-control-command": TypeAdapter(ReplayControlCommand),
    "replay-build-result": TypeAdapter(ReplayBuildResult),
}


def contract_kinds() -> tuple[str, ...]:
    return tuple(sorted(_CONTRACT_ADAPTERS))


def get_adapter(kind: str) -> TypeAdapter[Any]:
    try:
        return _CONTRACT_ADAPTERS[kind]
    except KeyError as exc:
        available = ", ".join(contract_kinds())
        raise ValueError(f"unknown contract kind {kind!r}; available kinds: {available}") from exc


def validate_contract(kind: str, data: Any) -> Any:
    return get_adapter(kind).validate_python(data)


def contract_schema(kind: str) -> dict[str, Any]:
    return get_adapter(kind).json_schema()
