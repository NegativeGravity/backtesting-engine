from __future__ import annotations

from decimal import Decimal

from pydantic import Field, NonNegativeInt, field_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import Side
from vex_contracts.identifiers import SymbolCode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class Mt5BridgeConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    terminal_path: str | None = None
    login: NonNegativeInt | None = None
    password_env: str = "MT5_PASSWORD"
    server: str | None = None
    portable: bool = False
    timeout_ms: NonNegativeInt = 60000
    symbols: tuple[SymbolCode, ...] = Field(min_length=1)
    sample_volumes: tuple[Decimal, ...] = (Decimal("0.01"), Decimal("0.10"), Decimal("1.00"))
    sample_distance_points: NonNegativeInt = 100
    snapshot_version: str = "1.0.0"

    @field_validator("sample_volumes", mode="before")
    @classmethod
    def parse_volumes(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                item if isinstance(item, Decimal) else Decimal(str(item)) for item in value
            )
        return value


class Mt5OrderMapping(ContractModel):
    side: Side
    market_order_type: NonNegativeInt
    position_type: NonNegativeInt
