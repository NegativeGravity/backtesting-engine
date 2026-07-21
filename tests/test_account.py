from decimal import Decimal

import pytest
from pydantic import ValidationError

from vex_contracts.account import AccountConfig


def test_account_config_accepts_valid_margin_levels() -> None:
    config = AccountConfig(
        currency="USD",
        initial_balance="100000",
        leverage="100",
        margin_call_level_percent="100",
        stop_out_level_percent="50",
    )

    assert config.initial_balance == Decimal("100000")
    assert config.leverage == Decimal("100")


def test_account_config_rejects_inverted_margin_levels() -> None:
    with pytest.raises(ValidationError):
        AccountConfig(
            currency="USD",
            initial_balance="100000",
            leverage="100",
            margin_call_level_percent="50",
            stop_out_level_percent="100",
        )
