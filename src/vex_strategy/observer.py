from typing import Protocol

from vex_broker.models import BrokerResult
from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.market import Bar


class StrategyRunObserver(Protocol):
    def on_execution_bar(
        self,
        bar: Bar,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None: ...

    def on_broker_result(
        self,
        event_time_ns: int,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None: ...


class NullStrategyRunObserver:
    def on_execution_bar(
        self,
        bar: Bar,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None:
        return None

    def on_broker_result(
        self,
        event_time_ns: int,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None:
        return None
