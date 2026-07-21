from decimal import Decimal

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import PositionSide, PositionStatus
from vex_contracts.identifiers import CurrencyCode, Identifier, SymbolCode


class Position(ContractModel):
    position_id: Identifier
    run_id: Identifier
    strategy_instance_id: Identifier
    symbol: SymbolCode
    side: PositionSide
    status: PositionStatus
    volume_lots: Decimal = Field(gt=0)
    average_entry_price_ticks: Decimal
    opened_time_ns: NonNegativeInt
    current_price_ticks: int | None = None
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    closed_time_ns: int | None = Field(default=None, ge=0)
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    spread_cost: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_cost: Decimal = Field(default=Decimal("0"), ge=0)
    swap: Decimal = Decimal("0")

    @field_validator(
        "volume_lots",
        "average_entry_price_ticks",
        "realized_pnl",
        "unrealized_pnl",
        "commission",
        "spread_cost",
        "slippage_cost",
        "swap",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_position(self) -> "Position":
        if self.status is PositionStatus.OPEN and self.closed_time_ns is not None:
            raise ValueError("open positions must not define closed_time_ns")
        if self.status is PositionStatus.CLOSED and self.closed_time_ns is None:
            raise ValueError("closed positions require closed_time_ns")
        if self.closed_time_ns is not None and self.closed_time_ns < self.opened_time_ns:
            raise ValueError("closed_time_ns must not precede opened_time_ns")
        return self


class Trade(ContractModel):
    trade_id: Identifier
    position_id: Identifier
    run_id: Identifier
    strategy_instance_id: Identifier
    symbol: SymbolCode
    side: PositionSide
    volume_lots: Decimal = Field(gt=0)
    entry_time_ns: NonNegativeInt
    exit_time_ns: NonNegativeInt
    entry_price_ticks: Decimal
    exit_price_ticks: Decimal
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    gross_pnl: Decimal
    commission: Decimal = Field(ge=0)
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    swap: Decimal
    net_pnl: Decimal
    initial_risk: Decimal | None = Field(default=None, gt=0)
    realized_r_multiple: Decimal | None = None
    mae: Decimal = Field(default=Decimal("0"), ge=0)
    mfe: Decimal = Field(default=Decimal("0"), ge=0)
    intrabar_ambiguous: bool = False
    exit_reason: str = Field(min_length=1, max_length=160)

    @field_validator(
        "volume_lots",
        "entry_price_ticks",
        "exit_price_ticks",
        "gross_pnl",
        "commission",
        "spread_cost",
        "slippage_cost",
        "swap",
        "net_pnl",
        "initial_risk",
        "realized_r_multiple",
        "mae",
        "mfe",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_trade(self) -> "Trade":
        if self.exit_time_ns < self.entry_time_ns:
            raise ValueError("exit_time_ns must not precede entry_time_ns")
        expected_net = (
            self.gross_pnl - self.commission - self.spread_cost - self.slippage_cost + self.swap
        )
        if self.net_pnl != expected_net:
            raise ValueError("net_pnl must equal the sum of trade components")
        if self.initial_risk is None and self.realized_r_multiple is not None:
            raise ValueError("realized_r_multiple requires initial_risk")
        return self


class AccountSnapshot(ContractModel):
    run_id: Identifier
    timestamp_ns: NonNegativeInt
    sequence: NonNegativeInt
    currency: CurrencyCode
    balance: Decimal
    equity: Decimal
    margin: Decimal = Field(ge=0)
    free_margin: Decimal
    margin_level_percent: Decimal | None = None
    floating_pnl: Decimal
    peak_equity: Decimal
    drawdown_amount: Decimal = Field(ge=0)
    drawdown_percent: Decimal = Field(ge=0)

    @field_validator(
        "balance",
        "equity",
        "margin",
        "free_margin",
        "margin_level_percent",
        "floating_pnl",
        "peak_equity",
        "drawdown_amount",
        "drawdown_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))
