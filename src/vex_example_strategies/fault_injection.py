from time import sleep

from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext


class SlowStartStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> None:
        sleep(1)


class CrashingStartStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> None:
        raise RuntimeError("intentional strategy failure")
