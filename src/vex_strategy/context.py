from pydantic import BaseModel

from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.run import BacktestRunConfig
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import FormingBar, StrategyOutputBatch, StrategyRuntimeConfig
from vex_strategy.actions import StrategyOutputCollector
from vex_strategy.chart import StrategyChartApi
from vex_strategy.logging import StrategyLogger
from vex_strategy.market import MarketDataView
from vex_strategy.orders import StrategyOrderApi
from vex_strategy.portfolio import PortfolioView


class StrategyContext:
    def __init__(
        self,
        run_config: BacktestRunConfig,
        descriptor: StrategyDescriptor,
        runtime_config: StrategyRuntimeConfig,
        parameters: BaseModel,
        initial_snapshot: BrokerStateSnapshot,
    ) -> None:
        self.run_id = run_config.run_id
        self.strategy_id = descriptor.strategy_id
        self.instance_id = run_config.strategy.instance_id
        self.parameters = parameters
        self.market = MarketDataView(
            run_config.subscriptions,
            runtime_config.history_limit_per_series,
        )
        self.portfolio = PortfolioView(initial_snapshot)
        self._collector = StrategyOutputCollector(
            self.instance_id,
            runtime_config.max_actions_per_callback,
            runtime_config.max_chart_commands_per_callback,
            runtime_config.max_log_records_per_callback,
        )
        self.orders = StrategyOrderApi(
            self._collector,
            self.market,
            self.portfolio,
            run_config.execution_timeframe,
        )
        self.chart = StrategyChartApi(self._collector, self.instance_id)
        self.log = StrategyLogger(self._collector)

    @property
    def now_ns(self) -> int:
        return self.market.current_time_ns

    def apply_warmup(self, bars: tuple[Bar, ...], forming_bars: tuple[FormingBar, ...]) -> None:
        if bars:
            latest_time = max(bar.close_time_ns for bar in bars)
            self.market.set_time(latest_time)
            self.market.apply_closed_bars(bars)
        if forming_bars:
            observed_time = max(bar.observed_time_ns for bar in forming_bars)
            self.market.set_time(observed_time)
            self.market.set_forming_bars(forming_bars)

    def update_cycle(
        self,
        time_ns: int,
        bars: tuple[Bar, ...],
        forming_bars: tuple[FormingBar, ...],
        snapshot: BrokerStateSnapshot,
        broker_events: tuple[EventEnvelope[dict[str, JsonValue]], ...],
    ) -> None:
        self.market.set_time(time_ns)
        self.market.apply_closed_bars(bars)
        self.market.set_forming_bars(forming_bars)
        self.portfolio.update(snapshot, broker_events)

    def begin_callback(self, orders_allowed: bool = True) -> None:
        self._collector.begin(self.now_ns, orders_allowed)

    def drain(self) -> StrategyOutputBatch:
        return self._collector.drain()
