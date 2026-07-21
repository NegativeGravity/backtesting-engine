from decimal import Decimal

from vex_contracts.chart import (
    AppendSeriesPointCommand,
    CandleSeriesPoint,
    ChartDrawing,
    ChartPoint,
    ClearLayerCommand,
    DeclarePaneCommand,
    DeclareSeriesCommand,
    DeleteDrawingCommand,
    FillAppearance,
    HorizontalLineDrawing,
    LabelDrawing,
    LineAppearance,
    MarkerDrawing,
    PaneSpec,
    RectangleDrawing,
    RiskRewardDrawing,
    ScalarSeriesPoint,
    SeriesSpec,
    TrendLineDrawing,
    UpsertDrawingCommand,
)
from vex_contracts.enums import (
    ChartLineStyle,
    ChartMarkerPosition,
    ChartMarkerShape,
    ChartSeriesKind,
    PositionSide,
)
from vex_contracts.timeframes import Timeframe
from vex_strategy.actions import StrategyOutputCollector


class StrategyChartApi:
    def __init__(self, collector: StrategyOutputCollector, default_layer_id: str) -> None:
        self._collector = collector
        self._default_layer_id = default_layer_id
        self._panes: set[str] = set()
        self._series: set[str] = set()
        self._drawing_revisions: dict[tuple[str, str], int] = {}

    def declare_pane(
        self,
        pane_id: str,
        title: str,
        height_weight: Decimal | str | int | float = Decimal("1"),
        overlay: bool = False,
    ) -> None:
        if pane_id in self._panes:
            return
        self._collector.append_chart(
            DeclarePaneCommand(
                pane=PaneSpec(
                    pane_id=pane_id,
                    title=title,
                    height_weight=Decimal(str(height_weight)),
                    overlay=overlay,
                )
            )
        )
        self._panes.add(pane_id)

    def declare_series(
        self,
        series_id: str,
        pane_id: str,
        title: str,
        kind: ChartSeriesKind = ChartSeriesKind.LINE,
        color: str = "#2962FF",
        layer_id: str | None = None,
        line_width: int = 2,
        price_scale_id: str = "right",
        visible: bool = True,
    ) -> None:
        if pane_id not in self._panes:
            raise ValueError(f"pane must be declared before its series: {pane_id}")
        if series_id in self._series:
            return
        self._collector.append_chart(
            DeclareSeriesCommand(
                series=SeriesSpec(
                    series_id=series_id,
                    layer_id=self._layer(layer_id),
                    pane_id=pane_id,
                    title=title,
                    kind=kind,
                    color=color,
                    line_width=line_width,
                    price_scale_id=price_scale_id,
                    visible=visible,
                )
            )
        )
        self._series.add(series_id)

    def plot_scalar(
        self,
        series_id: str,
        value: Decimal | str | int | float,
        time_ns: int | None = None,
    ) -> None:
        self._require_series(series_id)
        self._collector.append_chart(
            AppendSeriesPointCommand(
                series_id=series_id,
                point=ScalarSeriesPoint(
                    time_ns=self._time(time_ns),
                    value=Decimal(str(value)),
                ),
            )
        )

    def plot_candle(
        self,
        series_id: str,
        open_value: Decimal | str | int | float,
        high_value: Decimal | str | int | float,
        low_value: Decimal | str | int | float,
        close_value: Decimal | str | int | float,
        time_ns: int | None = None,
    ) -> None:
        self._require_series(series_id)
        self._collector.append_chart(
            AppendSeriesPointCommand(
                series_id=series_id,
                point=CandleSeriesPoint(
                    time_ns=self._time(time_ns),
                    open=Decimal(str(open_value)),
                    high=Decimal(str(high_value)),
                    low=Decimal(str(low_value)),
                    close=Decimal(str(close_value)),
                ),
            )
        )

    def trend_line(
        self,
        drawing_id: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int,
        start_price_ticks: int | Decimal,
        end_time_ns: int,
        end_price_ticks: int | Decimal,
        color: str = "#2962FF",
        width: int = 2,
        style: ChartLineStyle = ChartLineStyle.SOLID,
        extend_left: bool = False,
        extend_right: bool = False,
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            TrendLineDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                start=ChartPoint(
                    time_ns=start_time_ns,
                    price_ticks=Decimal(str(start_price_ticks)),
                ),
                end=ChartPoint(
                    time_ns=end_time_ns,
                    price_ticks=Decimal(str(end_price_ticks)),
                ),
                appearance=LineAppearance(color=color, width=width, style=style),
                extend_left=extend_left,
                extend_right=extend_right,
            )
        )

    def horizontal_line(
        self,
        drawing_id: str,
        symbol: str,
        timeframe: Timeframe,
        price_ticks: int | Decimal,
        color: str = "#2962FF",
        width: int = 1,
        style: ChartLineStyle = ChartLineStyle.SOLID,
        label: str | None = None,
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            HorizontalLineDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                price_ticks=Decimal(str(price_ticks)),
                appearance=LineAppearance(color=color, width=width, style=style),
                label=label,
            )
        )

    def rectangle(
        self,
        drawing_id: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int,
        start_price_ticks: int | Decimal,
        end_time_ns: int,
        end_price_ticks: int | Decimal,
        border_color: str = "#2962FF",
        fill_color: str = "#2962FF",
        fill_opacity: Decimal | str | int | float = Decimal("0.2"),
        border_width: int = 1,
        border_style: ChartLineStyle = ChartLineStyle.SOLID,
        label: str | None = None,
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            RectangleDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                start=ChartPoint(
                    time_ns=start_time_ns,
                    price_ticks=Decimal(str(start_price_ticks)),
                ),
                end=ChartPoint(
                    time_ns=end_time_ns,
                    price_ticks=Decimal(str(end_price_ticks)),
                ),
                border=LineAppearance(
                    color=border_color,
                    width=border_width,
                    style=border_style,
                ),
                fill=FillAppearance(
                    color=fill_color,
                    opacity=Decimal(str(fill_opacity)),
                ),
                label=label,
            )
        )

    def marker(
        self,
        drawing_id: str,
        symbol: str,
        timeframe: Timeframe,
        time_ns: int,
        shape: ChartMarkerShape,
        position: ChartMarkerPosition,
        color: str,
        price_ticks: int | Decimal | None = None,
        text: str | None = None,
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            MarkerDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                time_ns=time_ns,
                price_ticks=(None if price_ticks is None else Decimal(str(price_ticks))),
                shape=shape,
                position=position,
                color=color,
                text=text,
            )
        )

    def label(
        self,
        drawing_id: str,
        symbol: str,
        timeframe: Timeframe,
        time_ns: int,
        price_ticks: int | Decimal,
        text: str,
        text_color: str = "#FFFFFF",
        background_color: str = "#2962FF",
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            LabelDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                anchor=ChartPoint(
                    time_ns=time_ns,
                    price_ticks=Decimal(str(price_ticks)),
                ),
                text=text,
                text_color=text_color,
                background_color=background_color,
            )
        )

    def risk_reward(
        self,
        drawing_id: str,
        trade_id: str,
        symbol: str,
        timeframe: Timeframe,
        side: PositionSide,
        entry_time_ns: int,
        entry_price_ticks: int | Decimal,
        stop_price_ticks: int | Decimal,
        target_price_ticks: int | Decimal,
        exit_time_ns: int | None = None,
        exit_price_ticks: int | Decimal | None = None,
        label: str | None = None,
        layer_id: str | None = None,
        visible: bool = True,
        locked: bool = True,
        z_index: int = 0,
    ) -> None:
        resolved_layer = self._layer(layer_id)
        self._upsert(
            RiskRewardDrawing(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                symbol=symbol,
                timeframe=timeframe,
                revision=self._next_revision(resolved_layer, drawing_id),
                visible=visible,
                locked=locked,
                z_index=z_index,
                trade_id=trade_id,
                side=side,
                entry_time_ns=entry_time_ns,
                exit_time_ns=exit_time_ns,
                entry_price_ticks=Decimal(str(entry_price_ticks)),
                stop_price_ticks=Decimal(str(stop_price_ticks)),
                target_price_ticks=Decimal(str(target_price_ticks)),
                exit_price_ticks=(
                    None if exit_price_ticks is None else Decimal(str(exit_price_ticks))
                ),
                risk_fill=FillAppearance(color="#F23645", opacity=Decimal("0.20")),
                reward_fill=FillAppearance(color="#089981", opacity=Decimal("0.20")),
                entry_line=LineAppearance(color="#2962FF", width=1),
                stop_line=LineAppearance(color="#F23645", width=1),
                target_line=LineAppearance(color="#089981", width=1),
                label=label,
            )
        )

    def upsert(self, drawing: ChartDrawing) -> None:
        key = (drawing.layer_id, drawing.drawing_id)
        expected_revision = self._drawing_revisions.get(key, -1) + 1
        normalized = drawing.model_copy(update={"revision": expected_revision})
        self._drawing_revisions[key] = expected_revision
        self._upsert(normalized)

    def delete(self, drawing_id: str, layer_id: str | None = None) -> None:
        resolved_layer = self._layer(layer_id)
        revision = self._next_revision(resolved_layer, drawing_id)
        self._collector.append_chart(
            DeleteDrawingCommand(
                drawing_id=drawing_id,
                layer_id=resolved_layer,
                revision=revision,
            )
        )

    def clear_layer(self, layer_id: str | None = None) -> None:
        resolved_layer = self._layer(layer_id)
        self._collector.append_chart(ClearLayerCommand(layer_id=resolved_layer))
        self._drawing_revisions = {
            key: revision
            for key, revision in self._drawing_revisions.items()
            if key[0] != resolved_layer
        }

    def _upsert(self, drawing: ChartDrawing) -> None:
        self._collector.append_chart(UpsertDrawingCommand(drawing=drawing))

    def _next_revision(self, layer_id: str, drawing_id: str) -> int:
        key = (layer_id, drawing_id)
        revision = self._drawing_revisions.get(key, -1) + 1
        self._drawing_revisions[key] = revision
        return revision

    def _layer(self, layer_id: str | None) -> str:
        return layer_id or self._default_layer_id

    def _time(self, time_ns: int | None) -> int:
        return self._collector.current_time_ns if time_ns is None else time_ns

    def _require_series(self, series_id: str) -> None:
        if series_id not in self._series:
            raise ValueError(f"series must be declared before plotting: {series_id}")
