from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import PositionMode
from vex_contracts.identifiers import CurrencyCode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class AccountConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    currency: CurrencyCode = "USD"
    initial_balance: Decimal = Field(gt=0)
    leverage: Decimal = Field(gt=0)
    position_mode: PositionMode = PositionMode.HEDGING
    margin_call_level_percent: Decimal = Field(default=Decimal("100"), ge=0)
    stop_out_level_percent: Decimal = Field(default=Decimal("50"), ge=0)
    allow_negative_balance: bool = False

    @field_validator(
        "initial_balance",
        "leverage",
        "margin_call_level_percent",
        "stop_out_level_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_margin_levels(self) -> "AccountConfig":
        if self.stop_out_level_percent > self.margin_call_level_percent:
            raise ValueError("stop_out_level_percent must not exceed margin_call_level_percent")
        return self
