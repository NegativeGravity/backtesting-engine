from typing import TYPE_CHECKING, Any

from vex_strategy.base import EmptyStrategyParameters, Strategy
from vex_strategy.context import StrategyContext
from vex_strategy.exceptions import (
    StrategyActionError,
    StrategyError,
    StrategyExecutionError,
    StrategyFeedbackLimitError,
    StrategyLoadError,
    StrategyMarketDataError,
    StrategyOutputLimitError,
    StrategyProcessError,
    StrategyTimeoutError,
)
from vex_strategy.isolation import IsolatedStrategyProcess

if TYPE_CHECKING:
    from vex_strategy.runner import StrategyBacktestRunner


def __getattr__(name: str) -> Any:
    if name == "StrategyBacktestRunner":
        from vex_strategy.runner import StrategyBacktestRunner

        return StrategyBacktestRunner
    raise AttributeError(name)


__all__ = [
    "EmptyStrategyParameters",
    "IsolatedStrategyProcess",
    "Strategy",
    "StrategyActionError",
    "StrategyBacktestRunner",
    "StrategyContext",
    "StrategyError",
    "StrategyExecutionError",
    "StrategyFeedbackLimitError",
    "StrategyLoadError",
    "StrategyMarketDataError",
    "StrategyOutputLimitError",
    "StrategyProcessError",
    "StrategyTimeoutError",
]
