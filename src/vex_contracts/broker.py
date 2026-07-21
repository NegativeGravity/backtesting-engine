from decimal import Decimal

from pydantic import Field, NonNegativeInt, field_validator

from vex_contracts.base import ContractModel
from vex_contracts.identifiers import Identifier, Sha256Hex
from vex_contracts.orders import Order
from vex_contracts.positions import AccountSnapshot, Position
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class BrokerStateSnapshot(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    run_id: Identifier
    timestamp_ns: NonNegativeInt
    event_sequence: NonNegativeInt
    account: AccountSnapshot
    orders: tuple[Order, ...] = ()
    positions: tuple[Position, ...] = ()


class BrokerSimulationReport(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    report_id: Identifier
    run_id: Identifier
    processed_bars: NonNegativeInt
    event_count: NonNegativeInt
    order_count: NonNegativeInt
    fill_count: NonNegativeInt
    trade_count: NonNegativeInt
    open_position_count: NonNegativeInt
    rejected_order_count: NonNegativeInt
    cancelled_order_count: NonNegativeInt
    final_account: AccountSnapshot
    gross_pnl: Decimal
    net_pnl: Decimal
    commission: Decimal = Field(ge=0)
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    swap: Decimal
    deterministic_digest: Sha256Hex

    @field_validator(
        "gross_pnl",
        "net_pnl",
        "commission",
        "spread_cost",
        "slippage_cost",
        "swap",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))
