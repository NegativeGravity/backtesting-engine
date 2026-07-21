from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext


class ReplaceMeStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> None:
        context.chart.declare_pane("main", "Price", overlay=True)

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        del context, bar

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        del context, event

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        del context, reason
