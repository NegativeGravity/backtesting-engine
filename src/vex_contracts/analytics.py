from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, NonNegativeInt, PositiveInt, field_validator

from vex_contracts.base import ContractModel
from vex_contracts.identifiers import CurrencyCode, Identifier
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class AnalyticsConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    annualization_days: PositiveInt = 252
    risk_free_rate_percent: Decimal = Decimal("0")
    confidence_level: Decimal = Field(default=Decimal("0.95"), gt=0, lt=1)
    rolling_window_days: PositiveInt = 30
    minimum_annualization_days: PositiveInt = 30

    @field_validator("risk_free_rate_percent", "confidence_level", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class EquityCurvePoint(ContractModel):
    time_ns: NonNegativeInt
    balance: Decimal
    equity: Decimal
    floating_pnl: Decimal
    margin: Decimal = Field(ge=0)
    drawdown_amount: Decimal = Field(ge=0)
    drawdown_percent: Decimal = Field(ge=0)

    @field_validator(
        "balance",
        "equity",
        "floating_pnl",
        "margin",
        "drawdown_amount",
        "drawdown_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class PeriodReturnPoint(ContractModel):
    time_ns: NonNegativeInt
    period: str = Field(min_length=1, max_length=32)
    equity: Decimal
    pnl: Decimal
    return_percent: Decimal

    @field_validator("equity", "pnl", "return_percent", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class RollingMetricPoint(ContractModel):
    time_ns: NonNegativeInt
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    annualized_volatility_percent: Decimal | None = None
    rolling_drawdown_percent: Decimal = Field(ge=0)

    @field_validator(
        "sharpe_ratio",
        "sortino_ratio",
        "annualized_volatility_percent",
        "rolling_drawdown_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class PerformanceMetrics(ContractModel):
    initial_balance: Decimal
    final_balance: Decimal
    final_equity: Decimal
    gross_profit: Decimal = Field(ge=0)
    gross_loss: Decimal = Field(ge=0)
    gross_pnl: Decimal
    net_pnl: Decimal
    total_return_percent: Decimal
    cagr_percent: Decimal | None = None
    profit_factor: Decimal | None = Field(default=None, ge=0)
    expectancy: Decimal
    average_trade: Decimal
    median_trade: Decimal
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    payoff_ratio: Decimal | None = Field(default=None, ge=0)
    best_trade: Decimal | None = None
    worst_trade: Decimal | None = None
    average_r_multiple: Decimal | None = None
    median_r_multiple: Decimal | None = None
    system_quality_number: Decimal | None = None

    @field_validator("*", mode="before")
    @classmethod
    def parse_decimal_fields(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
        return value


class RiskMetrics(ContractModel):
    max_drawdown_amount: Decimal = Field(ge=0)
    max_drawdown_percent: Decimal = Field(ge=0)
    max_drawdown_duration_minutes: Decimal = Field(ge=0)
    max_recovery_duration_minutes: Decimal | None = Field(default=None, ge=0)
    average_drawdown_percent: Decimal = Field(ge=0)
    annualized_volatility_percent: Decimal | None = Field(default=None, ge=0)
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    calmar_ratio: Decimal | None = None
    recovery_factor: Decimal | None = None
    ulcer_index: Decimal = Field(ge=0)
    value_at_risk_percent: Decimal | None = Field(default=None, ge=0)
    conditional_value_at_risk_percent: Decimal | None = Field(default=None, ge=0)
    best_day_return_percent: Decimal | None = None
    worst_day_return_percent: Decimal | None = None

    @field_validator("*", mode="before")
    @classmethod
    def parse_decimal_fields(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
        return value


class TradeBehaviorMetrics(ContractModel):
    total_trades: NonNegativeInt
    winning_trades: NonNegativeInt
    losing_trades: NonNegativeInt
    breakeven_trades: NonNegativeInt
    long_trades: NonNegativeInt
    short_trades: NonNegativeInt
    win_rate_percent: Decimal = Field(ge=0, le=100)
    loss_rate_percent: Decimal = Field(ge=0, le=100)
    average_holding_minutes: Decimal = Field(ge=0)
    median_holding_minutes: Decimal = Field(ge=0)
    longest_holding_minutes: Decimal = Field(ge=0)
    max_consecutive_wins: NonNegativeInt
    max_consecutive_losses: NonNegativeInt
    time_in_market_percent: Decimal = Field(ge=0, le=100)
    ambiguous_trade_count: NonNegativeInt
    average_mae: Decimal = Field(ge=0)
    average_mfe: Decimal = Field(ge=0)
    average_mfe_capture_percent: Decimal | None = None

    @field_validator(
        "win_rate_percent",
        "loss_rate_percent",
        "average_holding_minutes",
        "median_holding_minutes",
        "longest_holding_minutes",
        "time_in_market_percent",
        "average_mae",
        "average_mfe",
        "average_mfe_capture_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class ExecutionCostMetrics(ContractModel):
    commission: Decimal = Field(ge=0)
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    swap: Decimal
    total_cost: Decimal
    average_cost_per_trade: Decimal
    cost_to_gross_profit_percent: Decimal | None = None
    commission_share_percent: Decimal = Field(ge=0, le=100)
    spread_share_percent: Decimal = Field(ge=0, le=100)
    slippage_share_percent: Decimal = Field(ge=0, le=100)

    @field_validator("*", mode="before")
    @classmethod
    def parse_decimal_fields(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
        return value


class PeriodicPerformance(ContractModel):
    period: str = Field(min_length=1, max_length=32)
    start_time_ns: NonNegativeInt
    end_time_ns: NonNegativeInt
    opening_equity: Decimal
    closing_equity: Decimal
    net_pnl: Decimal
    return_percent: Decimal
    max_drawdown_percent: Decimal = Field(ge=0)
    trade_count: NonNegativeInt
    winning_trades: NonNegativeInt
    losing_trades: NonNegativeInt
    win_rate_percent: Decimal = Field(ge=0, le=100)

    @field_validator(
        "opening_equity",
        "closing_equity",
        "net_pnl",
        "return_percent",
        "max_drawdown_percent",
        "win_rate_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class BreakdownRow(ContractModel):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    trade_count: NonNegativeInt
    winning_trades: NonNegativeInt
    losing_trades: NonNegativeInt
    win_rate_percent: Decimal = Field(ge=0, le=100)
    net_pnl: Decimal
    average_pnl: Decimal
    profit_factor: Decimal | None = Field(default=None, ge=0)
    average_r_multiple: Decimal | None = None
    average_holding_minutes: Decimal = Field(ge=0)

    @field_validator(
        "win_rate_percent",
        "net_pnl",
        "average_pnl",
        "profit_factor",
        "average_r_multiple",
        "average_holding_minutes",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class DistributionBucket(ContractModel):
    label: str = Field(min_length=1, max_length=80)
    lower_bound: Decimal
    upper_bound: Decimal
    count: NonNegativeInt
    percentage: Decimal = Field(ge=0, le=100)

    @field_validator("lower_bound", "upper_bound", "percentage", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class DrawdownEpisode(ContractModel):
    start_time_ns: NonNegativeInt
    trough_time_ns: NonNegativeInt
    recovery_time_ns: NonNegativeInt | None = None
    max_drawdown_amount: Decimal = Field(ge=0)
    max_drawdown_percent: Decimal = Field(ge=0)
    duration_minutes: Decimal = Field(ge=0)
    recovery_minutes: Decimal | None = Field(default=None, ge=0)

    @field_validator(
        "max_drawdown_amount",
        "max_drawdown_percent",
        "duration_minutes",
        "recovery_minutes",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class AnalyticsReport(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    report_id: Identifier
    run_id: Identifier
    generated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    start_time_ns: NonNegativeInt
    end_time_ns: NonNegativeInt
    currency: CurrencyCode
    config: AnalyticsConfig
    performance: PerformanceMetrics
    risk: RiskMetrics
    trades: TradeBehaviorMetrics
    costs: ExecutionCostMetrics
    equity_curve: tuple[EquityCurvePoint, ...]
    daily_returns: tuple[PeriodReturnPoint, ...]
    rolling_metrics: tuple[RollingMetricPoint, ...]
    monthly_performance: tuple[PeriodicPerformance, ...]
    yearly_performance: tuple[PeriodicPerformance, ...]
    drawdown_episodes: tuple[DrawdownEpisode, ...]
    side_breakdown: tuple[BreakdownRow, ...]
    symbol_breakdown: tuple[BreakdownRow, ...]
    exit_reason_breakdown: tuple[BreakdownRow, ...]
    weekday_breakdown: tuple[BreakdownRow, ...]
    hour_breakdown: tuple[BreakdownRow, ...]
    pnl_distribution: tuple[DistributionBucket, ...]
    r_multiple_distribution: tuple[DistributionBucket, ...]
    duration_distribution: tuple[DistributionBucket, ...]


class AnalyticsComparisonRow(ContractModel):
    run_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    net_pnl: Decimal
    total_return_percent: Decimal
    max_drawdown_percent: Decimal = Field(ge=0)
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    profit_factor: Decimal | None = Field(default=None, ge=0)
    win_rate_percent: Decimal = Field(ge=0, le=100)
    total_trades: NonNegativeInt

    @field_validator(
        "net_pnl",
        "total_return_percent",
        "max_drawdown_percent",
        "sharpe_ratio",
        "sortino_ratio",
        "profit_factor",
        "win_rate_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class AnalyticsComparisonReport(ContractModel):
    rows: tuple[AnalyticsComparisonRow, ...]
    sort_by: Literal[
        "net_pnl",
        "total_return_percent",
        "max_drawdown_percent",
        "sharpe_ratio",
        "profit_factor",
    ] = "net_pnl"
