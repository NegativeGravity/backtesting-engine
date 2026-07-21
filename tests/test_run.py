from pathlib import Path

import pytest
from pydantic import ValidationError

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml


def test_example_run_config_is_valid(project_root: Path) -> None:
    config = BacktestRunConfig.model_validate(load_yaml(project_root / "examples/configs/run.yaml"))

    assert config.execution_timeframe.value == "M1"
    assert config.account.initial_balance == 100000


def test_run_requires_execution_timeframe_subscription(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/run.yaml")
    payload["execution_timeframe"] = "M30"

    with pytest.raises(ValidationError):
        BacktestRunConfig.model_validate(payload)


def test_run_requires_matching_commission_currency(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/run.yaml")
    payload["execution"]["commission"]["currency"] = "EUR"

    with pytest.raises(ValidationError):
        BacktestRunConfig.model_validate(payload)
