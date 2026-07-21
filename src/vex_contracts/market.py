from decimal import Decimal

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.identifiers import SymbolCode
from vex_contracts.timeframes import Timeframe


class Bar(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    open_time_ns: NonNegativeInt
    close_time_ns: PositiveInt
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    tick_volume: NonNegativeInt = 0
    real_volume: Decimal = Field(default=Decimal("0"), ge=0)
    source_spread_points: NonNegativeInt = 0
    sequence: NonNegativeInt

    @field_validator("real_volume", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_bar(self) -> "Bar":
        if self.open_time_ns >= self.close_time_ns:
            raise ValueError("open_time_ns must be earlier than close_time_ns")
        if self.high_ticks < max(self.open_ticks, self.close_ticks, self.low_ticks):
            raise ValueError("high_ticks is inconsistent with OHLC values")
        if self.low_ticks > min(self.open_ticks, self.close_ticks, self.high_ticks):
            raise ValueError("low_ticks is inconsistent with OHLC values")
        expected_seconds = self.timeframe.seconds
        if expected_seconds is not None:
            actual_ns = self.close_time_ns - self.open_time_ns
            if actual_ns != expected_seconds * 1_000_000_000:
                raise ValueError("bar duration does not match timeframe")
        return self
