from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.broker import BrokerSimulationReport
from vex_contracts.chart import ChartCommand
from vex_contracts.enums import OrderType, Side, TimeInForce
from vex_contracts.identifiers import Identifier, Sha256Hex, SymbolCode
from vex_contracts.market import Bar
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class StrategyRuntimeConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    isolation_mode: Literal["process", "in_process"] = "process"
    startup_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    callback_timeout_seconds: float = Field(default=5.0, gt=0, le=300)
    shutdown_timeout_seconds: float = Field(default=5.0, gt=0, le=300)
    history_limit_per_series: PositiveInt = 10000
    warmup_bars_per_series: NonNegativeInt = 500
    max_actions_per_callback: PositiveInt = 1000
    max_chart_commands_per_callback: PositiveInt = 10000
    max_log_records_per_callback: PositiveInt = 1000
    max_feedback_rounds: NonNegativeInt = 4
    fail_on_action_error: bool = True

    @model_validator(mode="after")
    def validate_history_limits(self) -> "StrategyRuntimeConfig":
        if self.warmup_bars_per_series > self.history_limit_per_series:
            raise ValueError("warmup_bars_per_series must not exceed history_limit_per_series")
        return self


class FormingBar(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    open_time_ns: NonNegativeInt
    close_time_ns: PositiveInt
    observed_time_ns: NonNegativeInt
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    tick_volume: NonNegativeInt = 0
    real_volume: Decimal = Field(default=Decimal("0"), ge=0)
    source_spread_points: NonNegativeInt = 0

    @field_validator("real_volume", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_forming_bar(self) -> "FormingBar":
        if self.open_time_ns >= self.close_time_ns:
            raise ValueError("open_time_ns must be earlier than close_time_ns")
        if not self.open_time_ns < self.observed_time_ns < self.close_time_ns:
            raise ValueError("observed_time_ns must be inside the forming bar interval")
        if self.high_ticks < max(self.open_ticks, self.close_ticks, self.low_ticks):
            raise ValueError("high_ticks is inconsistent with OHLC values")
        if self.low_ticks > min(self.open_ticks, self.close_ticks, self.high_ticks):
            raise ValueError("low_ticks is inconsistent with OHLC values")
        return self


class OrderIntent(ContractModel):
    client_order_id: Identifier
    symbol: SymbolCode
    side: Side
    order_type: OrderType
    volume_lots: Decimal | None = Field(default=None, gt=0)
    price_ticks: int | None = None
    sizing_price_ticks: int | None = None
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    expiration_time_ns: int | None = Field(default=None, gt=0)
    reduce_only: bool = False
    position_id: Identifier | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("volume_lots", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_intent(self) -> "OrderIntent":
        if self.order_type is OrderType.MARKET and self.price_ticks is not None:
            raise ValueError("market orders must not define price_ticks")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP} and self.price_ticks is None:
            raise ValueError("limit and stop orders require price_ticks")
        if self.volume_lots is None and self.sizing_price_ticks is None:
            raise ValueError("risk-sized orders require sizing_price_ticks")
        if self.time_in_force is TimeInForce.DAY and self.expiration_time_ns is None:
            raise ValueError("day orders require expiration_time_ns")
        if self.reduce_only and self.position_id is None:
            raise ValueError("reduce_only orders require position_id")
        reference = self.price_ticks if self.price_ticks is not None else self.sizing_price_ticks
        if reference is not None and self.side is Side.BUY:
            if self.stop_loss_ticks is not None and self.stop_loss_ticks >= reference:
                raise ValueError("buy stop loss must be below the reference price")
            if self.take_profit_ticks is not None and self.take_profit_ticks <= reference:
                raise ValueError("buy take profit must be above the reference price")
        if reference is not None and self.side is Side.SELL:
            if self.stop_loss_ticks is not None and self.stop_loss_ticks <= reference:
                raise ValueError("sell stop loss must be above the reference price")
            if self.take_profit_ticks is not None and self.take_profit_ticks >= reference:
                raise ValueError("sell take profit must be below the reference price")
        return self


class StrategyActionBase(ContractModel):
    action_id: Identifier
    requested_time_ns: NonNegativeInt


class SubmitOrderAction(StrategyActionBase):
    action_type: Literal["submit_order"] = "submit_order"
    intent: OrderIntent


class CancelOrderAction(StrategyActionBase):
    action_type: Literal["cancel_order"] = "cancel_order"
    order_id: Identifier
    reason: str = Field(default="strategy_requested", min_length=1, max_length=160)


class ModifyOrderAction(StrategyActionBase):
    action_type: Literal["modify_order"] = "modify_order"
    order_id: Identifier
    price_ticks: int | None = None
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    expiration_time_ns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_updates(self) -> "ModifyOrderAction":
        if all(
            value is None
            for value in (
                self.price_ticks,
                self.stop_loss_ticks,
                self.take_profit_ticks,
                self.expiration_time_ns,
            )
        ):
            raise ValueError("modify order action requires at least one update")
        return self


class ModifyPositionProtectionAction(StrategyActionBase):
    action_type: Literal["modify_position_protection"] = "modify_position_protection"
    position_id: Identifier
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None


type StrategyAction = Annotated[
    SubmitOrderAction | CancelOrderAction | ModifyOrderAction | ModifyPositionProtectionAction,
    Field(discriminator="action_type"),
]


class StrategyLogRecord(ContractModel):
    sequence: PositiveInt
    time_ns: NonNegativeInt
    level: Literal["debug", "info", "warning", "error"]
    message: str = Field(min_length=1, max_length=2000)
    fields: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class StrategyCallbackStatistics(ContractModel):
    start: NonNegativeInt = 0
    bar: NonNegativeInt = 0
    order_update: NonNegativeInt = 0
    stop: NonNegativeInt = 0

    @property
    def total(self) -> int:
        return self.start + self.bar + self.order_update + self.stop


class StrategyBacktestReport(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    report_id: Identifier
    run_id: Identifier
    strategy_id: Identifier
    strategy_instance_id: Identifier
    processed_close_batches: NonNegativeInt
    processed_execution_bars: NonNegativeInt
    callbacks: StrategyCallbackStatistics
    action_count: NonNegativeInt
    chart_command_count: NonNegativeInt
    log_record_count: NonNegativeInt
    feedback_round_count: NonNegativeInt
    action_error_count: NonNegativeInt
    broker_report: BrokerSimulationReport
    output_digest: Sha256Hex
    deterministic_digest: Sha256Hex


class StrategyOutputBatch(ContractModel):
    actions: tuple[StrategyAction, ...] = ()
    chart_commands: tuple[ChartCommand, ...] = ()
    logs: tuple[StrategyLogRecord, ...] = ()
    callback_statistics: StrategyCallbackStatistics = Field(
        default_factory=StrategyCallbackStatistics
    )


class StrategyWarmupData(ContractModel):
    bars: tuple[Bar, ...] = ()
    forming_bars: tuple[FormingBar, ...] = ()
