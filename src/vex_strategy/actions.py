from collections.abc import Iterable
from typing import Literal

from vex_contracts.chart import ChartCommand
from vex_contracts.strategy_runtime import StrategyAction, StrategyLogRecord, StrategyOutputBatch
from vex_strategy.exceptions import StrategyOutputLimitError


class StrategyOutputCollector:
    def __init__(
        self,
        strategy_instance_id: str,
        max_actions: int,
        max_chart_commands: int,
        max_logs: int,
    ) -> None:
        self._strategy_instance_id = strategy_instance_id
        self._max_actions = max_actions
        self._max_chart_commands = max_chart_commands
        self._max_logs = max_logs
        self._action_sequence = 0
        self._client_order_sequence = 0
        self._log_sequence = 0
        self._current_time_ns = 0
        self._orders_allowed = True
        self._actions: list[StrategyAction] = []
        self._chart_commands: list[ChartCommand] = []
        self._logs: list[StrategyLogRecord] = []

    @property
    def current_time_ns(self) -> int:
        return self._current_time_ns

    @property
    def orders_allowed(self) -> bool:
        return self._orders_allowed

    def begin(self, time_ns: int, orders_allowed: bool = True) -> None:
        self._current_time_ns = time_ns
        self._orders_allowed = orders_allowed
        self._actions.clear()
        self._chart_commands.clear()
        self._logs.clear()

    def next_action_id(self) -> str:
        self._action_sequence += 1
        return f"{self._strategy_instance_id}:action:{self._action_sequence:012d}"

    def next_client_order_id(self) -> str:
        self._client_order_sequence += 1
        return f"{self._strategy_instance_id}:order:{self._client_order_sequence:012d}"

    def append_action(self, action: StrategyAction) -> None:
        if not self._orders_allowed:
            raise StrategyOutputLimitError("order actions are disabled for this callback")
        if len(self._actions) >= self._max_actions:
            raise StrategyOutputLimitError("strategy action limit exceeded")
        self._actions.append(action)

    def append_chart(self, command: ChartCommand) -> None:
        if len(self._chart_commands) >= self._max_chart_commands:
            raise StrategyOutputLimitError("chart command limit exceeded")
        self._chart_commands.append(command)

    def append_log(
        self,
        level: Literal["debug", "info", "warning", "error"],
        message: str,
        fields: dict[str, str | int | float | bool | None],
    ) -> None:
        if len(self._logs) >= self._max_logs:
            raise StrategyOutputLimitError("strategy log limit exceeded")
        self._log_sequence += 1
        self._logs.append(
            StrategyLogRecord(
                sequence=self._log_sequence,
                time_ns=self._current_time_ns,
                level=level,
                message=message,
                fields=fields,
            )
        )

    def extend(self, outputs: Iterable[StrategyOutputBatch]) -> StrategyOutputBatch:
        actions: list[StrategyAction] = []
        chart_commands: list[ChartCommand] = []
        logs: list[StrategyLogRecord] = []
        for output in outputs:
            actions.extend(output.actions)
            chart_commands.extend(output.chart_commands)
            logs.extend(output.logs)
        return StrategyOutputBatch(
            actions=tuple(actions),
            chart_commands=tuple(chart_commands),
            logs=tuple(logs),
        )

    def drain(self) -> StrategyOutputBatch:
        return StrategyOutputBatch(
            actions=tuple(self._actions),
            chart_commands=tuple(self._chart_commands),
            logs=tuple(self._logs),
        )
