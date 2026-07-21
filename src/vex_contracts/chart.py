from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import (
    ChartCommandType,
    ChartDrawingKind,
    ChartLineStyle,
    ChartMarkerPosition,
    ChartMarkerShape,
    ChartSeriesKind,
    PositionSide,
)
from vex_contracts.identifiers import HexColor, Identifier, SymbolCode
from vex_contracts.timeframes import Timeframe


class ChartPoint(ContractModel):
    time_ns: NonNegativeInt
    price_ticks: Decimal

    @field_validator("price_ticks", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class LineAppearance(ContractModel):
    color: HexColor
    width: int = Field(default=1, ge=1, le=8)
    style: ChartLineStyle = ChartLineStyle.SOLID


class FillAppearance(ContractModel):
    color: HexColor
    opacity: Decimal = Field(default=Decimal("0.2"), ge=0, le=1)

    @field_validator("opacity", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class PaneSpec(ContractModel):
    pane_id: Identifier
    title: str = Field(min_length=1, max_length=120)
    height_weight: Decimal = Field(default=Decimal("1"), gt=0)
    overlay: bool = False

    @field_validator("height_weight", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class SeriesSpec(ContractModel):
    series_id: Identifier
    layer_id: Identifier
    pane_id: Identifier
    title: str = Field(min_length=1, max_length=120)
    kind: ChartSeriesKind
    color: HexColor
    line_width: int = Field(default=2, ge=1, le=8)
    price_scale_id: str = Field(default="right", min_length=1, max_length=64)
    visible: bool = True


class ScalarSeriesPoint(ContractModel):
    point_type: Literal["scalar"] = "scalar"
    time_ns: NonNegativeInt
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class CandleSeriesPoint(ContractModel):
    point_type: Literal["candle"] = "candle"
    time_ns: NonNegativeInt
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @model_validator(mode="after")
    def validate_ohlc(self) -> "CandleSeriesPoint":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC values")
        return self


type SeriesPoint = Annotated[
    ScalarSeriesPoint | CandleSeriesPoint,
    Field(discriminator="point_type"),
]


class DrawingBase(ContractModel):
    drawing_id: Identifier
    layer_id: Identifier
    symbol: SymbolCode
    timeframe: Timeframe
    revision: NonNegativeInt = 0
    visible: bool = True
    locked: bool = True
    z_index: int = 0


class TrendLineDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.TREND_LINE] = ChartDrawingKind.TREND_LINE
    start: ChartPoint
    end: ChartPoint
    appearance: LineAppearance
    extend_left: bool = False
    extend_right: bool = False


class HorizontalLineDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.HORIZONTAL_LINE] = ChartDrawingKind.HORIZONTAL_LINE
    price_ticks: Decimal
    appearance: LineAppearance
    label: str | None = Field(default=None, max_length=160)

    @field_validator("price_ticks", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))


class RectangleDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.RECTANGLE] = ChartDrawingKind.RECTANGLE
    start: ChartPoint
    end: ChartPoint
    border: LineAppearance
    fill: FillAppearance
    label: str | None = Field(default=None, max_length=160)


class MarkerDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.MARKER] = ChartDrawingKind.MARKER
    time_ns: NonNegativeInt
    price_ticks: Decimal | None = None
    shape: ChartMarkerShape
    position: ChartMarkerPosition
    color: HexColor
    text: str | None = Field(default=None, max_length=160)

    @field_validator("price_ticks", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class LabelDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.LABEL] = ChartDrawingKind.LABEL
    anchor: ChartPoint
    text: str = Field(min_length=1, max_length=500)
    text_color: HexColor
    background_color: HexColor


class RiskRewardDrawing(DrawingBase):
    kind: Literal[ChartDrawingKind.RISK_REWARD] = ChartDrawingKind.RISK_REWARD
    trade_id: Identifier
    side: PositionSide
    entry_time_ns: NonNegativeInt
    exit_time_ns: NonNegativeInt | None = None
    entry_price_ticks: Decimal
    stop_price_ticks: Decimal
    target_price_ticks: Decimal
    exit_price_ticks: Decimal | None = None
    risk_fill: FillAppearance
    reward_fill: FillAppearance
    entry_line: LineAppearance
    stop_line: LineAppearance
    target_line: LineAppearance
    label: str | None = Field(default=None, max_length=240)

    @field_validator(
        "entry_price_ticks",
        "stop_price_ticks",
        "target_price_ticks",
        "exit_price_ticks",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_levels(self) -> "RiskRewardDrawing":
        if (
            self.side is PositionSide.LONG
            and not self.stop_price_ticks < self.entry_price_ticks < self.target_price_ticks
        ):
            raise ValueError("long risk-reward levels are invalid")
        if (
            self.side is PositionSide.SHORT
            and not self.target_price_ticks < self.entry_price_ticks < self.stop_price_ticks
        ):
            raise ValueError("short risk-reward levels are invalid")
        if self.exit_time_ns is not None and self.exit_time_ns < self.entry_time_ns:
            raise ValueError("exit_time_ns must not precede entry_time_ns")
        return self


type ChartDrawing = Annotated[
    TrendLineDrawing
    | HorizontalLineDrawing
    | RectangleDrawing
    | MarkerDrawing
    | LabelDrawing
    | RiskRewardDrawing,
    Field(discriminator="kind"),
]


class DeclarePaneCommand(ContractModel):
    command_type: Literal[ChartCommandType.DECLARE_PANE] = ChartCommandType.DECLARE_PANE
    pane: PaneSpec


class DeclareSeriesCommand(ContractModel):
    command_type: Literal[ChartCommandType.DECLARE_SERIES] = ChartCommandType.DECLARE_SERIES
    series: SeriesSpec


class AppendSeriesPointCommand(ContractModel):
    command_type: Literal[ChartCommandType.APPEND_SERIES_POINT] = (
        ChartCommandType.APPEND_SERIES_POINT
    )
    series_id: Identifier
    point: SeriesPoint


class UpsertDrawingCommand(ContractModel):
    command_type: Literal[ChartCommandType.UPSERT_DRAWING] = ChartCommandType.UPSERT_DRAWING
    drawing: ChartDrawing


class DeleteDrawingCommand(ContractModel):
    command_type: Literal[ChartCommandType.DELETE_DRAWING] = ChartCommandType.DELETE_DRAWING
    drawing_id: Identifier
    layer_id: Identifier
    revision: NonNegativeInt


class ClearLayerCommand(ContractModel):
    command_type: Literal[ChartCommandType.CLEAR_LAYER] = ChartCommandType.CLEAR_LAYER
    layer_id: Identifier


type ChartCommand = Annotated[
    DeclarePaneCommand
    | DeclareSeriesCommand
    | AppendSeriesPointCommand
    | UpsertDrawingCommand
    | DeleteDrawingCommand
    | ClearLayerCommand,
    Field(discriminator="command_type"),
]
