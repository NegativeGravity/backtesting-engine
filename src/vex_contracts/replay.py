from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue, NonNegativeInt, PositiveInt, field_validator, model_validator

from vex_contracts.analytics import AnalyticsReport
from vex_contracts.base import ContractModel
from vex_contracts.broker import BrokerSimulationReport
from vex_contracts.identifiers import Identifier, Sha256Hex, SymbolCode
from vex_contracts.orders import Fill, Order
from vex_contracts.positions import AccountSnapshot, Position, Trade
from vex_contracts.strategy_runtime import StrategyBacktestReport
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class ReplayBundleManifest(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    bundle_id: Identifier
    run_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    strategy_id: Identifier
    strategy_instance_id: Identifier
    dataset_id: Identifier
    dataset_version: str = Field(min_length=1, max_length=64)
    default_symbol: SymbolCode
    default_timeframe: Timeframe
    execution_timeframe: Timeframe
    available_symbols: tuple[SymbolCode, ...]
    available_timeframes: tuple[Timeframe, ...]
    start_time_ns: NonNegativeInt
    end_time_ns: PositiveInt
    import_report_path: str = Field(min_length=1, max_length=500)
    sqlite_path: str = Field(min_length=1, max_length=500)
    symbol_profile_paths: tuple[str, ...]
    strategy_report_path: str = Field(min_length=1, max_length=500)
    run_config_path: str = Field(min_length=1, max_length=500)
    strategy_descriptor_path: str = Field(min_length=1, max_length=500)
    runtime_config_path: str = Field(min_length=1, max_length=500)
    analytics_report_path: str | None = Field(default=None, min_length=1, max_length=500)
    strategy_source_path: str | None = Field(default=None, min_length=1, max_length=500)
    strategy_source_sha256: Sha256Hex | None = None
    max_close_batches: PositiveInt | None = None
    timeline_item_count: NonNegativeInt = 0
    account_snapshot_count: NonNegativeInt = 0
    equity_point_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_manifest(self) -> "ReplayBundleManifest":
        if self.end_time_ns <= self.start_time_ns:
            raise ValueError("end_time_ns must be later than start_time_ns")
        if self.default_symbol not in self.available_symbols:
            raise ValueError("default_symbol must be available")
        if self.default_timeframe not in self.available_timeframes:
            raise ValueError("default_timeframe must be available")
        if self.execution_timeframe not in self.available_timeframes:
            raise ValueError("execution_timeframe must be available")
        if (self.strategy_source_path is None) != (self.strategy_source_sha256 is None):
            raise ValueError(
                "strategy_source_path and strategy_source_sha256 must be provided together"
            )
        return self


class ReplayBar(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    sequence: NonNegativeInt
    open_time_ns: NonNegativeInt
    close_time_ns: PositiveInt
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: NonNegativeInt = 0
    real_volume: Decimal = Field(default=Decimal("0"), ge=0)
    source_spread_points: NonNegativeInt = 0
    is_complete: bool = True

    @field_validator("open", "high", "low", "close", "real_volume", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_bar(self) -> "ReplayBar":
        if self.close_time_ns <= self.open_time_ns:
            raise ValueError("close_time_ns must be later than open_time_ns")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC values")
        return self


class ReplayTimelineItem(ContractModel):
    sequence: PositiveInt
    time_ns: NonNegativeInt
    kind: Literal[
        "broker_event",
        "chart_command",
        "strategy_action",
        "strategy_log",
        "account_snapshot",
    ]
    payload: dict[str, JsonValue]


class ReplayMetrics(ContractModel):
    initial_balance: Decimal
    final_balance: Decimal
    final_equity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    commission: Decimal = Field(ge=0)
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    swap: Decimal
    total_trades: NonNegativeInt
    winning_trades: NonNegativeInt
    losing_trades: NonNegativeInt
    long_trades: NonNegativeInt
    short_trades: NonNegativeInt
    win_rate: Decimal = Field(ge=0, le=100)
    profit_factor: Decimal | None = Field(default=None, ge=0)
    average_r_multiple: Decimal | None = None
    max_drawdown_amount: Decimal = Field(ge=0)
    max_drawdown_percent: Decimal = Field(ge=0)

    @field_validator(
        "initial_balance",
        "final_balance",
        "final_equity",
        "gross_pnl",
        "net_pnl",
        "commission",
        "spread_cost",
        "slippage_cost",
        "swap",
        "win_rate",
        "profit_factor",
        "average_r_multiple",
        "max_drawdown_amount",
        "max_drawdown_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class ReplayRunDescriptor(ContractModel):
    run_id: Identifier
    name: str
    strategy_id: Identifier
    strategy_instance_id: Identifier
    dataset_id: Identifier
    default_symbol: SymbolCode
    default_timeframe: Timeframe
    execution_timeframe: Timeframe
    available_symbols: tuple[SymbolCode, ...]
    available_timeframes: tuple[Timeframe, ...]
    start_time_ns: NonNegativeInt
    end_time_ns: PositiveInt
    metrics: ReplayMetrics


class ReplayCatalog(ContractModel):
    runs: tuple[ReplayRunDescriptor, ...]


class ReplayBootstrap(ContractModel):
    run: ReplayRunDescriptor
    symbol: SymbolCode
    timeframe: Timeframe
    cursor_sequence: NonNegativeInt
    cursor_time_ns: NonNegativeInt
    progress: Decimal = Field(ge=0, le=1)
    price_digits: NonNegativeInt
    price_tick_size: Decimal = Field(gt=0)
    bars: tuple[ReplayBar, ...]
    timeline: tuple[ReplayTimelineItem, ...]
    account: AccountSnapshot
    orders: tuple[Order, ...]
    positions: tuple[Position, ...]
    fills: tuple[Fill, ...]
    trades: tuple[Trade, ...]
    strategy_report: StrategyBacktestReport
    broker_report: BrokerSimulationReport

    @field_validator("progress", "price_tick_size", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class ReplayFrame(ContractModel):
    frame_type: Literal["advance", "reset", "state", "completed"]
    cursor_sequence: NonNegativeInt
    cursor_time_ns: NonNegativeInt
    progress: Decimal = Field(ge=0, le=1)
    playing: bool
    speed: Decimal = Field(gt=0)
    bars: tuple[ReplayBar, ...] = ()
    timeline: tuple[ReplayTimelineItem, ...] = ()
    account: AccountSnapshot | None = None

    @field_validator("progress", "speed", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class ReplayControlCommand(ContractModel):
    action: Literal[
        "play",
        "pause",
        "step_forward",
        "step_backward",
        "seek_time",
        "seek_progress",
        "set_speed",
        "set_timeframe",
        "reset",
    ]
    value: str | int | float | None = None


class ReplayBuildResult(ContractModel):
    manifest: ReplayBundleManifest
    strategy_report: StrategyBacktestReport
    analytics_report: AnalyticsReport
    database_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    analytics_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
