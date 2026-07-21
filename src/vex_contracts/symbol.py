from decimal import ROUND_FLOOR, Decimal

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import CalculationMode
from vex_contracts.identifiers import CurrencyCode, Identifier, SemanticVersion, SymbolCode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class SymbolProfile(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    profile_id: Identifier
    version: SemanticVersion
    symbol: SymbolCode
    calculation_mode: CalculationMode
    currency_base: CurrencyCode
    currency_profit: CurrencyCode
    currency_margin: CurrencyCode
    digits: NonNegativeInt = Field(le=12)
    point: Decimal = Field(gt=0)
    trade_tick_size: Decimal = Field(gt=0)
    trade_tick_value: Decimal = Field(gt=0)
    trade_tick_value_profit: Decimal | None = Field(default=None, gt=0)
    trade_tick_value_loss: Decimal | None = Field(default=None, gt=0)
    trade_contract_size: Decimal = Field(gt=0)
    volume_min: Decimal = Field(gt=0)
    volume_max: Decimal = Field(gt=0)
    volume_step: Decimal = Field(gt=0)
    stops_level_points: NonNegativeInt = 0
    freeze_level_points: NonNegativeInt = 0
    margin_initial: Decimal = Field(default=Decimal("0"), ge=0)
    margin_maintenance: Decimal = Field(default=Decimal("0"), ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_tick_value_profit",
        "trade_tick_value_loss",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "margin_initial",
        "margin_maintenance",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_market_rules(self) -> "SymbolProfile":
        if self.volume_min > self.volume_max:
            raise ValueError("volume_min must not exceed volume_max")
        if self.volume_step > self.volume_max:
            raise ValueError("volume_step must not exceed volume_max")
        point_scale = Decimal(1).scaleb(-int(self.digits))
        if self.point != point_scale:
            raise ValueError("point must match digits")
        tick_ratio = self.trade_tick_size / self.point
        if tick_ratio != tick_ratio.to_integral_value():
            raise ValueError("trade_tick_size must be an integer multiple of point")
        return self

    def normalize_volume(self, requested: Decimal) -> Decimal:
        if requested < self.volume_min:
            raise ValueError("requested volume is below volume_min")
        capped = min(requested, self.volume_max)
        steps = ((capped - self.volume_min) / self.volume_step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        return self.volume_min + steps * self.volume_step

    def price_to_ticks(self, price: Decimal) -> int:
        ratio = price / self.trade_tick_size
        if ratio != ratio.to_integral_value():
            raise ValueError("price is not aligned to trade_tick_size")
        return int(ratio)

    def ticks_to_price(self, ticks: int) -> Decimal:
        return Decimal(ticks) * self.trade_tick_size
