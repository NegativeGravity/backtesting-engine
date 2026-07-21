import pytest

from vex_example_strategies.sdk_smoke import SdkSmokeStrategy
from vex_strategy.exceptions import StrategyLoadError
from vex_strategy.loader import load_strategy_class


def test_loader_resolves_strategy_subclass() -> None:
    loaded = load_strategy_class("vex_example_strategies.sdk_smoke:SdkSmokeStrategy")

    assert loaded is SdkSmokeStrategy


def test_loader_rejects_non_strategy_object() -> None:
    with pytest.raises(StrategyLoadError):
        load_strategy_class("decimal:Decimal")
