from pathlib import Path

from pydantic import BaseModel

from vex_broker.simulator import BrokerSimulator
from vex_contracts.chart import UpsertDrawingCommand
from vex_contracts.enums import ChartMarkerPosition, ChartMarkerShape
from vex_contracts.market import Bar
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_strategy.context import StrategyContext

NS = 1_000_000_000


def test_context_emits_order_and_versioned_chart_commands(project_root: Path) -> None:
    run = BacktestRunConfig.model_validate(
        load_yaml(project_root / "examples/configs/run_strategy_smoke.yaml")
    )
    descriptor = StrategyDescriptor.model_validate(
        load_yaml(project_root / "examples/configs/strategy_sdk_smoke.yaml")
    )
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    context = StrategyContext(
        run,
        descriptor,
        StrategyRuntimeConfig(warmup_bars_per_series=0),
        SdkParameters(),
        broker.state_snapshot,
    )
    bar = Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=0,
        close_time_ns=60 * NS,
        open_ticks=260000,
        high_ticks=260010,
        low_ticks=259990,
        close_ticks=260005,
        sequence=0,
    )
    context.update_cycle(60 * NS, (bar,), (), broker.state_snapshot, ())
    context.begin_callback()
    context.orders.buy_market("XAUUSD", volume_lots="0.10")
    context.chart.marker(
        "context.marker",
        "XAUUSD",
        Timeframe.M1,
        60 * NS,
        ChartMarkerShape.ARROW_UP,
        ChartMarkerPosition.BELOW_BAR,
        "#089981",
    )
    context.chart.marker(
        "context.marker",
        "XAUUSD",
        Timeframe.M1,
        60 * NS,
        ChartMarkerShape.ARROW_UP,
        ChartMarkerPosition.BELOW_BAR,
        "#089981",
    )

    output = context.drain()

    assert len(output.actions) == 1
    commands = [
        command for command in output.chart_commands if isinstance(command, UpsertDrawingCommand)
    ]
    assert commands[0].drawing.revision == 0
    assert commands[1].drawing.revision == 1


class SdkParameters(BaseModel):
    pass
