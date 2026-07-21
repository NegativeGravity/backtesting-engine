from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, PositiveInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import PositionSizingMode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class FixedLotSizingConfig(ContractModel):
    mode: Literal[PositionSizingMode.FIXED_LOT] = PositionSizingMode.FIXED_LOT
    volume_lots: Decimal = Field(gt=0)

    @field_validator("volume_lots", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class RiskPercentSizingConfig(ContractModel):
    mode: Literal[PositionSizingMode.RISK_PERCENT] = PositionSizingMode.RISK_PERCENT
    risk_percent: Decimal = Field(gt=0, le=100)

    @field_validator("risk_percent", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class FixedCashRiskSizingConfig(ContractModel):
    mode: Literal[PositionSizingMode.FIXED_CASH_RISK] = PositionSizingMode.FIXED_CASH_RISK
    cash_amount: Decimal = Field(gt=0)

    @field_validator("cash_amount", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class StrategyDefinedSizingConfig(ContractModel):
    mode: Literal[PositionSizingMode.STRATEGY_DEFINED] = PositionSizingMode.STRATEGY_DEFINED


type PositionSizingConfig = Annotated[
    FixedLotSizingConfig
    | RiskPercentSizingConfig
    | FixedCashRiskSizingConfig
    | StrategyDefinedSizingConfig,
    Field(discriminator="mode"),
]


class RiskConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    default_sizing: PositionSizingConfig
    max_open_positions: PositiveInt = 1
    max_symbol_positions: PositiveInt = 1
    allow_pyramiding: bool = False
    allow_long: bool = True
    allow_short: bool = True
    max_margin_usage_percent: Decimal = Field(default=Decimal("80"), gt=0, le=100)

    @field_validator("max_margin_usage_percent", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_limits(self) -> "RiskConfig":
        if self.max_symbol_positions > self.max_open_positions:
            raise ValueError("max_symbol_positions must not exceed max_open_positions")
        if not self.allow_long and not self.allow_short:
            raise ValueError("at least one trade direction must be enabled")
        if self.allow_pyramiding and self.max_symbol_positions < 2:
            raise ValueError("pyramiding requires max_symbol_positions of at least two")
        return self
