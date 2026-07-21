import importlib
import inspect

from vex_strategy.base import Strategy
from vex_strategy.exceptions import StrategyLoadError


def load_strategy_class(entrypoint: str) -> type[Strategy]:
    module_name, separator, object_name = entrypoint.partition(":")
    if not separator or not module_name or not object_name:
        raise StrategyLoadError("strategy entrypoint must use module:object format")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise StrategyLoadError(f"failed to import strategy module {module_name!r}") from exc
    try:
        target = getattr(module, object_name)
    except AttributeError as exc:
        raise StrategyLoadError(
            f"strategy object {object_name!r} was not found in module {module_name!r}"
        ) from exc
    if not inspect.isclass(target) or not issubclass(target, Strategy):
        raise StrategyLoadError("strategy entrypoint must resolve to a Strategy subclass")
    return target
