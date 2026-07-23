from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import JsonValue

from vex_contracts.events import EventEnvelope
from vex_contracts.orders import Fill, Order
from vex_contracts.positions import AccountSnapshot, Position, Trade

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BrokerAggregateStatistics:
    commission: Decimal = ZERO
    spread_cost: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    realized_swap: Decimal = ZERO
    gross_profit: Decimal = ZERO
    gross_loss: Decimal = ZERO
    realized_r_sum: Decimal = ZERO
    realized_r_count: int = 0
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    rejected_orders: int = 0
    cancelled_orders: int = 0


@dataclass(slots=True)
class PositionState:
    position_id: str
    run_id: str
    strategy_instance_id: str
    symbol: str
    side: str
    volume_lots: Decimal
    average_entry_price_ticks: Decimal
    opened_time_ns: int
    entry_order_id: str
    entry_client_order_id: str = ""
    entry_tags: dict[str, str] = field(default_factory=dict)
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    stop_order_id: str | None = None
    take_profit_order_id: str | None = None
    entry_commission: Decimal = ZERO
    entry_spread_cost: Decimal = ZERO
    entry_slippage_cost: Decimal = ZERO
    margin: Decimal = ZERO
    swap: Decimal = ZERO
    mae: Decimal = ZERO
    mfe: Decimal = ZERO
    initial_risk: Decimal | None = None
    current_price_ticks: int | None = None
    last_update_time_ns: int = 0


@dataclass(slots=True)
class AccountState:
    balance: Decimal
    equity: Decimal
    margin: Decimal = ZERO
    free_margin: Decimal = ZERO
    floating_pnl: Decimal = ZERO
    peak_equity: Decimal = ZERO
    drawdown_amount: Decimal = ZERO
    drawdown_percent: Decimal = ZERO
    margin_level_percent: Decimal | None = None
    margin_call_active: bool = False


@dataclass(slots=True)
class BrokerState:
    account: AccountState
    orders: dict[str, Order] = field(default_factory=dict)
    positions: dict[str, PositionState] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    events: list[EventEnvelope[dict[str, JsonValue]]] = field(default_factory=list)
    last_bar_sequence: dict[str, int] = field(default_factory=dict)
    last_bar_close_time_ns: dict[str, int] = field(default_factory=dict)
    current_time_ns: int = 0
    event_sequence: int = 0


@dataclass(frozen=True, slots=True)
class BrokerResult:
    events: tuple[EventEnvelope[dict[str, JsonValue]], ...] = ()
    fills: tuple[Fill, ...] = ()
    trades: tuple[Trade, ...] = ()
    positions: tuple[Position, ...] = ()
    account_snapshot: AccountSnapshot | None = None

    @classmethod
    def empty(cls) -> "BrokerResult":
        return cls()
