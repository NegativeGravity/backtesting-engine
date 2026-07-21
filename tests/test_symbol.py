from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile


def test_symbol_profile_converts_prices_and_normalizes_volume(project_root: Path) -> None:
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )

    assert profile.price_to_ticks(Decimal("2650.25")) == 265025
    assert profile.ticks_to_price(265025) == Decimal("2650.25")
    assert profile.normalize_volume(Decimal("0.537")) == Decimal("0.53")


def test_symbol_profile_rejects_point_mismatch(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    payload["point"] = "0.1"

    with pytest.raises(ValidationError):
        SymbolProfile.model_validate(payload)
