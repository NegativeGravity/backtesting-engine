from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class DeadlinePacer:
    maximum_drift_seconds: float = 0.25
    _deadline: float | None = None

    def reset(self) -> None:
        self._deadline = None

    def delay(self, rate_per_second: float, now: float | None = None) -> float:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        current = time.monotonic() if now is None else now
        interval = 1.0 / rate_per_second
        if self._deadline is None or current - self._deadline > max(
            self.maximum_drift_seconds, interval * 4
        ):
            self._deadline = current
        self._deadline += interval
        return max(0.0, self._deadline - current)


def ui_publish_interval(rate_per_second: float) -> float:
    if rate_per_second <= 0:
        raise ValueError("rate_per_second must be positive")
    if rate_per_second <= 500:
        return 1.0 / 30.0
    if rate_per_second <= 5_000:
        return 1.0 / 20.0
    if rate_per_second <= 25_000:
        return 1.0 / 12.0
    return 1.0 / 8.0
