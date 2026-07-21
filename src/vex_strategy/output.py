import hashlib
import json
from pathlib import Path
from typing import TextIO

from pydantic import BaseModel

from vex_contracts.chart import ChartCommand
from vex_contracts.serialization import canonical_data, canonical_json
from vex_contracts.strategy_runtime import StrategyAction, StrategyLogRecord


class StrategyOutputRecorder:
    def __init__(
        self,
        output_directory: str | Path | None = None,
        retain_outputs: bool = False,
    ) -> None:
        self._hash = hashlib.sha256()
        self._retain_outputs = retain_outputs
        self._actions: list[StrategyAction] = []
        self._chart_commands: list[ChartCommand] = []
        self._logs: list[StrategyLogRecord] = []
        self._action_count = 0
        self._chart_command_count = 0
        self._log_count = 0
        self._streams: dict[str, TextIO] = {}
        if output_directory is not None:
            root = Path(output_directory)
            root.mkdir(parents=True, exist_ok=True)
            self._streams = {
                "action": (root / "strategy-actions.jsonl").open("w", encoding="utf-8"),
                "chart": (root / "chart-commands.jsonl").open("w", encoding="utf-8"),
                "log": (root / "strategy-logs.jsonl").open("w", encoding="utf-8"),
            }

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def chart_command_count(self) -> int:
        return self._chart_command_count

    @property
    def log_count(self) -> int:
        return self._log_count

    @property
    def actions(self) -> tuple[StrategyAction, ...]:
        return tuple(self._actions)

    @property
    def chart_commands(self) -> tuple[ChartCommand, ...]:
        return tuple(self._chart_commands)

    @property
    def logs(self) -> tuple[StrategyLogRecord, ...]:
        return tuple(self._logs)

    @property
    def digest(self) -> str:
        return self._hash.hexdigest()

    def record_action(self, action: StrategyAction) -> None:
        self._action_count += 1
        if self._retain_outputs:
            self._actions.append(action)
        self._record("action", action)

    def record_chart_command(self, command: ChartCommand) -> None:
        self._chart_command_count += 1
        if self._retain_outputs:
            self._chart_commands.append(command)
        self._record("chart", command)

    def record_log(self, record: StrategyLogRecord) -> None:
        self._log_count += 1
        if self._retain_outputs:
            self._logs.append(record)
        self._record("log", record)

    def close(self) -> None:
        for stream in self._streams.values():
            stream.close()
        self._streams.clear()

    def _record(self, kind: str, value: BaseModel) -> None:
        encoded = f"{kind}:{canonical_json(value)}\n".encode()
        self._hash.update(encoded)
        stream = self._streams.get(kind)
        if stream is not None:
            json.dump(
                canonical_data(value),
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            stream.write("\n")
