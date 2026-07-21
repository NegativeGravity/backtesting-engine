from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import PositionMode, PositionSide, Side
from vex_contracts.identifiers import CurrencyCode, Identifier, SemanticVersion, SymbolCode
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class Mt5TerminalSnapshot(ContractModel):
    name: str
    company: str
    build: NonNegativeInt
    connected: bool
    trade_allowed: bool
    tradeapi_disabled: bool
    path: str
    data_path: str
    commondata_path: str
    maxbars: NonNegativeInt
    ping_last_us: NonNegativeInt | None = None


class Mt5AccountSnapshot(ContractModel):
    login: NonNegativeInt
    server: str
    company: str
    name: str
    currency: CurrencyCode
    leverage: Decimal = Field(gt=0)
    position_mode: PositionMode
    trade_allowed: bool
    trade_expert: bool
    balance: Decimal
    credit: Decimal
    profit: Decimal
    equity: Decimal
    margin: Decimal = Field(ge=0)
    margin_free: Decimal
    margin_level: Decimal | None = None
    margin_so_mode: NonNegativeInt
    margin_so_call: Decimal = Field(ge=0)
    margin_so_so: Decimal = Field(ge=0)

    @field_validator(
        "leverage",
        "balance",
        "credit",
        "profit",
        "equity",
        "margin",
        "margin_free",
        "margin_level",
        "margin_so_call",
        "margin_so_so",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class Mt5SymbolSnapshot(ContractModel):
    symbol: SymbolCode
    path: str
    description: str
    currency_base: CurrencyCode
    currency_profit: CurrencyCode
    currency_margin: CurrencyCode
    digits: NonNegativeInt = Field(le=12)
    point: Decimal = Field(gt=0)
    spread_points: NonNegativeInt
    spread_float: bool
    trade_calc_mode: NonNegativeInt
    trade_mode: NonNegativeInt
    trade_execution_mode: NonNegativeInt
    order_mode: NonNegativeInt
    filling_mode: NonNegativeInt
    expiration_mode: NonNegativeInt
    stops_level_points: NonNegativeInt
    freeze_level_points: NonNegativeInt
    trade_tick_size: Decimal = Field(gt=0)
    trade_tick_value: Decimal = Field(gt=0)
    trade_tick_value_profit: Decimal = Field(gt=0)
    trade_tick_value_loss: Decimal = Field(gt=0)
    trade_contract_size: Decimal = Field(gt=0)
    volume_min: Decimal = Field(gt=0)
    volume_max: Decimal = Field(gt=0)
    volume_step: Decimal = Field(gt=0)
    volume_limit: Decimal = Field(ge=0)
    margin_initial: Decimal = Field(ge=0)
    margin_maintenance: Decimal = Field(ge=0)
    margin_hedged: Decimal = Field(ge=0)
    margin_hedged_use_leg: bool
    swap_mode: NonNegativeInt
    swap_long: Decimal
    swap_short: Decimal
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    last: Decimal = Field(ge=0)
    time_msc: NonNegativeInt

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
        "volume_limit",
        "margin_initial",
        "margin_maintenance",
        "margin_hedged",
        "swap_long",
        "swap_short",
        "bid",
        "ask",
        "last",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_prices(self) -> Mt5SymbolSnapshot:
        if self.ask < self.bid:
            raise ValueError("ask must not be below bid")
        if self.volume_min > self.volume_max:
            raise ValueError("volume_min must not exceed volume_max")
        if self.volume_step > self.volume_max:
            raise ValueError("volume_step must not exceed volume_max")
        expected_point = Decimal(1).scaleb(-int(self.digits))
        if self.point != expected_point:
            raise ValueError("point must match digits")
        return self


class Mt5CalculationSample(ContractModel):
    sample_id: Identifier
    symbol: SymbolCode
    side: Side
    volume_lots: Decimal = Field(gt=0)
    open_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    mt5_profit: Decimal
    mt5_margin: Decimal = Field(ge=0)

    @field_validator(
        "volume_lots",
        "open_price",
        "close_price",
        "mt5_profit",
        "mt5_margin",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @property
    def position_side(self) -> PositionSide:
        return PositionSide.LONG if self.side is Side.BUY else PositionSide.SHORT


class Mt5CompatibilitySnapshot(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    snapshot_id: Identifier
    version: SemanticVersion
    captured_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    terminal: Mt5TerminalSnapshot
    account: Mt5AccountSnapshot
    symbols: tuple[Mt5SymbolSnapshot, ...] = Field(min_length=1)
    calculation_samples: tuple[Mt5CalculationSample, ...] = Field(default_factory=tuple)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_symbols(self) -> Mt5CompatibilitySnapshot:
        symbols = [item.symbol for item in self.symbols]
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbol snapshots must be unique")
        available = set(symbols)
        missing = sorted({sample.symbol for sample in self.calculation_samples} - available)
        if missing:
            raise ValueError(f"calculation samples reference missing symbols: {', '.join(missing)}")
        if self.account.currency not in {item.currency_profit for item in self.symbols}:
            raise ValueError("at least one symbol profit currency must match account currency")
        return self


class Mt5ValidationTolerance(ContractModel):
    money_absolute: Decimal = Field(default=Decimal("0.01"), ge=0)
    money_relative_bps: Decimal = Field(default=Decimal("1"), ge=0)
    decimal_absolute: Decimal = Field(default=Decimal("0.00000001"), ge=0)

    @field_validator("money_absolute", "money_relative_bps", "decimal_absolute", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class Mt5ValidationConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    snapshot_path: str
    symbol_profile_paths: tuple[str, ...] = Field(min_length=1)
    run_config_path: str | None = None
    tolerance: Mt5ValidationTolerance = Field(default_factory=Mt5ValidationTolerance)
    fail_on_warning: bool = False


class Mt5ValidationCheck(ContractModel):
    check_id: Identifier
    category: Literal["terminal", "account", "symbol", "profit", "margin", "mapping"]
    status: Literal["passed", "warning", "failed", "skipped"]
    message: str
    symbol: SymbolCode | None = None
    sample_id: Identifier | None = None
    expected: str | None = None
    actual: str | None = None
    absolute_error: Decimal | None = Field(default=None, ge=0)
    relative_error_bps: Decimal | None = Field(default=None, ge=0)

    @field_validator("absolute_error", "relative_error_bps", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class Mt5CompatibilityReport(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    report_id: Identifier
    snapshot_id: Identifier
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    compatible: bool
    passed_checks: NonNegativeInt
    warning_checks: NonNegativeInt
    failed_checks: NonNegativeInt
    skipped_checks: NonNegativeInt
    checks: tuple[Mt5ValidationCheck, ...]
    generated_profiles: tuple[str, ...]
    deterministic_digest: str
