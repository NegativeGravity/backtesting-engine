from decimal import Decimal

import pytest
from pydantic import ValidationError

from vex_contracts.account import AccountConfig


def test_contracts_are_immutable() -> None:
    config = AccountConfig(
        currency="USD",
        initial_balance="100000",
        leverage="100",
    )

    with pytest.raises(ValidationError):
        config.initial_balance = Decimal("200000")


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AccountConfig.model_validate(
            {
                "currency": "USD",
                "initial_balance": "100000",
                "leverage": "100",
                "unexpected": True,
            }
        )
