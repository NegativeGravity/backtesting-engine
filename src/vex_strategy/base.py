from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar

if TYPE_CHECKING:
    from vex_strategy.context import StrategyContext


class EmptyStrategyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Strategy:
    parameter_model: ClassVar[type[BaseModel]] = EmptyStrategyParameters

    def __init__(self, parameters: dict[str, JsonValue]) -> None:
        self.parameters = self.parameter_model.model_validate(parameters)

    def on_start(self, context: StrategyContext) -> None:
        pass

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        pass

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        pass

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        pass
