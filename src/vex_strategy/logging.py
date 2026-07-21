from vex_strategy.actions import StrategyOutputCollector


class StrategyLogger:
    def __init__(self, collector: StrategyOutputCollector) -> None:
        self._collector = collector

    def debug(
        self,
        message: str,
        **fields: str | int | float | bool | None,
    ) -> None:
        self._collector.append_log("debug", message, fields)

    def info(
        self,
        message: str,
        **fields: str | int | float | bool | None,
    ) -> None:
        self._collector.append_log("info", message, fields)

    def warning(
        self,
        message: str,
        **fields: str | int | float | bool | None,
    ) -> None:
        self._collector.append_log("warning", message, fields)

    def error(
        self,
        message: str,
        **fields: str | int | float | bool | None,
    ) -> None:
        self._collector.append_log("error", message, fields)
