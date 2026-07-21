from decimal import Decimal

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import OrderStatus, OrderType, Side, TimeInForce
from vex_contracts.identifiers import Identifier, SymbolCode


class OrderRequest(ContractModel):
    client_order_id: Identifier
    run_id: Identifier
    strategy_instance_id: Identifier
    symbol: SymbolCode
    side: Side
    order_type: OrderType
    volume_lots: Decimal = Field(gt=0)
    created_time_ns: NonNegativeInt
    price_ticks: int | None = None
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    expiration_time_ns: int | None = Field(default=None, gt=0)
    reduce_only: bool = False
    position_id: Identifier | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("volume_lots", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_order_request(self) -> "OrderRequest":
        if self.order_type is OrderType.MARKET and self.price_ticks is not None:
            raise ValueError("market orders must not define price_ticks")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP} and self.price_ticks is None:
            raise ValueError("limit and stop orders require price_ticks")
        if self.time_in_force is TimeInForce.DAY and self.expiration_time_ns is None:
            raise ValueError("day orders require expiration_time_ns")
        if self.expiration_time_ns is not None and self.expiration_time_ns <= self.created_time_ns:
            raise ValueError("expiration_time_ns must be later than created_time_ns")
        if self.reduce_only and self.position_id is None:
            raise ValueError("reduce_only orders require position_id")
        if self.price_ticks is not None:
            if self.side is Side.BUY:
                if self.stop_loss_ticks is not None and self.stop_loss_ticks >= self.price_ticks:
                    raise ValueError("buy stop loss must be below entry price")
                if (
                    self.take_profit_ticks is not None
                    and self.take_profit_ticks <= self.price_ticks
                ):
                    raise ValueError("buy take profit must be above entry price")
            if self.side is Side.SELL:
                if self.stop_loss_ticks is not None and self.stop_loss_ticks <= self.price_ticks:
                    raise ValueError("sell stop loss must be above entry price")
                if (
                    self.take_profit_ticks is not None
                    and self.take_profit_ticks >= self.price_ticks
                ):
                    raise ValueError("sell take profit must be below entry price")
        return self


class Order(ContractModel):
    order_id: Identifier
    request: OrderRequest
    status: OrderStatus = OrderStatus.CREATED
    revision: NonNegativeInt = 0
    accepted_time_ns: int | None = Field(default=None, ge=0)
    activated_time_ns: int | None = Field(default=None, ge=0)
    terminal_time_ns: int | None = Field(default=None, ge=0)
    filled_volume_lots: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price_ticks: Decimal | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)

    @field_validator("filled_volume_lots", "average_fill_price_ticks", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_order(self) -> "Order":
        if self.filled_volume_lots > self.request.volume_lots:
            raise ValueError("filled volume must not exceed requested volume")
        if self.filled_volume_lots == 0 and self.average_fill_price_ticks is not None:
            raise ValueError("unfilled orders must not define average_fill_price_ticks")
        if self.filled_volume_lots > 0 and self.average_fill_price_ticks is None:
            raise ValueError("filled orders require average_fill_price_ticks")
        if (
            self.status is OrderStatus.FILLED
            and self.filled_volume_lots != self.request.volume_lots
        ):
            raise ValueError("filled orders require the full requested volume")
        if (
            self.status is OrderStatus.PARTIALLY_FILLED
            and not Decimal("0") < self.filled_volume_lots < self.request.volume_lots
        ):
            raise ValueError("partially filled orders require a partial volume")
        if self.status is OrderStatus.REJECTED and not self.rejection_reason:
            raise ValueError("rejected orders require rejection_reason")
        if self.status is not OrderStatus.REJECTED and self.rejection_reason is not None:
            raise ValueError("rejection_reason is only valid for rejected orders")
        terminal_statuses = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
        if self.status in terminal_statuses and self.terminal_time_ns is None:
            raise ValueError("terminal orders require terminal_time_ns")
        if self.status not in terminal_statuses and self.terminal_time_ns is not None:
            raise ValueError("non-terminal orders must not define terminal_time_ns")
        timestamps = [
            value
            for value in (
                self.accepted_time_ns,
                self.activated_time_ns,
                self.terminal_time_ns,
            )
            if value is not None
        ]
        if any(value < self.request.created_time_ns for value in timestamps):
            raise ValueError("order lifecycle timestamps must not precede created_time_ns")
        if (
            self.accepted_time_ns is not None
            and self.activated_time_ns is not None
            and self.activated_time_ns < self.accepted_time_ns
        ):
            raise ValueError("activated_time_ns must not precede accepted_time_ns")
        return self

    @property
    def remaining_volume_lots(self) -> Decimal:
        return self.request.volume_lots - self.filled_volume_lots


class Fill(ContractModel):
    fill_id: Identifier
    order_id: Identifier
    run_id: Identifier
    symbol: SymbolCode
    side: Side
    time_ns: NonNegativeInt
    price_ticks: int
    volume_lots: Decimal = Field(gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    spread_cost: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("volume_lots", "commission", "spread_cost", "slippage_cost", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class OrderModificationRequest(ContractModel):
    order_id: Identifier
    requested_time_ns: NonNegativeInt
    price_ticks: int | None = None
    stop_loss_ticks: int | None = None
    take_profit_ticks: int | None = None
    expiration_time_ns: int | None = Field(default=None, gt=0)


class OrderCancellationRequest(ContractModel):
    order_id: Identifier
    requested_time_ns: NonNegativeInt
    reason: str = Field(default="user_requested", min_length=1, max_length=160)
