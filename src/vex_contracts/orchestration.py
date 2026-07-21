from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt, PositiveInt

from vex_contracts.base import ContractModel
from vex_contracts.identifiers import Identifier
from vex_contracts.replay import ReplayRunDescriptor
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class StrategyPackageManifest(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    package_id: Identifier
    descriptor_path: str = "strategy.yaml"
    run_config_path: str = "run.yaml"
    runtime_config_path: str = "runtime.yaml"
    symbol_profile_paths: tuple[str, ...] = ("../../examples/configs/symbol_xauusd.yaml",)
    import_report_path: str = "../../data/cache/xauusd_mt5_2025_2026/2/import-report.json"
    enabled: bool = True


class StrategyPackageSummary(ContractModel):
    package_id: Identifier
    strategy_id: Identifier
    name: str
    version: str
    description: str
    entrypoint: str
    package_path: str
    tags: tuple[str, ...]
    enabled: bool


class LiveRunCreateRequest(ContractModel):
    strategy_package_id: Identifier
    run_id: Identifier | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    max_close_batches: PositiveInt | None = None
    start_paused: bool = True
    speed_bars_per_second: Decimal = Field(default=Decimal("10"), gt=0, le=500)


class LiveRunControlCommand(ContractModel):
    action: Literal[
        "play",
        "pause",
        "step_forward",
        "step_backward",
        "seek_progress",
        "reset",
        "set_speed",
        "cancel",
    ]
    value: str | int | float | None = None


class LiveRunState(ContractModel):
    run_id: Identifier
    strategy_package_id: Identifier
    status: Literal[
        "created",
        "starting",
        "paused",
        "running",
        "rewinding",
        "finalizing",
        "completed",
        "failed",
        "cancelled",
    ]
    playing: bool
    speed_bars_per_second: Decimal = Field(gt=0)
    processed_close_batches: NonNegativeInt = 0
    processed_execution_bars: NonNegativeInt = 0
    current_time_ns: NonNegativeInt
    progress: Decimal = Field(ge=0, le=1)
    max_close_batches: PositiveInt | None = None
    error: str | None = None
    replay_ready: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime
    descriptor: ReplayRunDescriptor


class LiveRunCatalog(ContractModel):
    strategies: tuple[StrategyPackageSummary, ...]
    runs: tuple[LiveRunState, ...]
