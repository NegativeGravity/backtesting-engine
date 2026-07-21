from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import (
    CommissionMode,
    GapPolicy,
    IntrabarPolicy,
    PendingOrderActivationPolicy,
    SignalExecutionPolicy,
    SlippageMode,
    SpreadMode,
)
from vex_contracts.identifiers import CurrencyCode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class FixedSpreadConfig(ContractModel):
    mode: Literal[SpreadMode.FIXED] = SpreadMode.FIXED
    points: NonNegativeInt


class HistoricalSpreadConfig(ContractModel):
    mode: Literal[SpreadMode.HISTORICAL] = SpreadMode.HISTORICAL
    fallback_points: NonNegativeInt = 0
    use_fallback_when_zero: bool = True
    minimum_points: NonNegativeInt = 0
    maximum_points: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "HistoricalSpreadConfig":
        if self.maximum_points is not None and self.maximum_points < self.minimum_points:
            raise ValueError("maximum_points must be greater than or equal to minimum_points")
        return self


type SpreadConfig = Annotated[
    FixedSpreadConfig | HistoricalSpreadConfig,
    Field(discriminator="mode"),
]


class NoCommissionConfig(ContractModel):
    mode: Literal[CommissionMode.NONE] = CommissionMode.NONE


class FixedPerOrderCommissionConfig(ContractModel):
    mode: Literal[CommissionMode.FIXED_PER_ORDER] = CommissionMode.FIXED_PER_ORDER
    amount: Decimal = Field(gt=0)
    currency: CurrencyCode

    @field_validator("amount", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class PerLotPerSideCommissionConfig(ContractModel):
    mode: Literal[CommissionMode.PER_LOT_PER_SIDE] = CommissionMode.PER_LOT_PER_SIDE
    amount_per_lot: Decimal = Field(gt=0)
    currency: CurrencyCode

    @field_validator("amount_per_lot", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class PerLotRoundTurnCommissionConfig(ContractModel):
    mode: Literal[CommissionMode.PER_LOT_ROUND_TURN] = CommissionMode.PER_LOT_ROUND_TURN
    amount_per_lot: Decimal = Field(gt=0)
    currency: CurrencyCode

    @field_validator("amount_per_lot", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class PercentageOfNotionalCommissionConfig(ContractModel):
    mode: Literal[CommissionMode.PERCENTAGE_OF_NOTIONAL] = CommissionMode.PERCENTAGE_OF_NOTIONAL
    rate_bps: Decimal = Field(gt=0)

    @field_validator("rate_bps", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


type CommissionConfig = Annotated[
    NoCommissionConfig
    | FixedPerOrderCommissionConfig
    | PerLotPerSideCommissionConfig
    | PerLotRoundTurnCommissionConfig
    | PercentageOfNotionalCommissionConfig,
    Field(discriminator="mode"),
]


class FixedSlippageConfig(ContractModel):
    mode: Literal[SlippageMode.FIXED] = SlippageMode.FIXED
    market_order_points: NonNegativeInt = 0
    stop_order_points: NonNegativeInt = 0
    limit_order_points: NonNegativeInt = 0


class ExecutionConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    signal_execution_policy: SignalExecutionPolicy = SignalExecutionPolicy.NEXT_BAR_OPEN
    pending_order_activation_policy: PendingOrderActivationPolicy = (
        PendingOrderActivationPolicy.NEXT_BAR
    )
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE
    gap_policy: GapPolicy = GapPolicy.MARKETABLE_OPEN
    spread: SpreadConfig
    commission: CommissionConfig
    slippage: FixedSlippageConfig = Field(default_factory=FixedSlippageConfig)
    allow_same_bar_exit_after_open_fill: bool = True

    @model_validator(mode="after")
    def validate_supported_modes(self) -> "ExecutionConfig":
        if self.slippage.mode is not SlippageMode.FIXED:
            raise ValueError("only fixed slippage is supported in the current contract version")
        return self
