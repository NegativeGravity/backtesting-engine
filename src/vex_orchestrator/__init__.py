from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vex_orchestrator.catalog import StrategyPackageCatalog
    from vex_orchestrator.manager import LiveBacktestManager

__all__ = ["LiveBacktestManager", "StrategyPackageCatalog"]


def __getattr__(name: str) -> Any:
    if name == "LiveBacktestManager":
        from vex_orchestrator.manager import LiveBacktestManager

        return LiveBacktestManager
    if name == "StrategyPackageCatalog":
        from vex_orchestrator.catalog import StrategyPackageCatalog

        return StrategyPackageCatalog
    raise AttributeError(name)
