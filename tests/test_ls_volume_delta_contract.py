from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor


def _audit_module(project_root: Path):
    path = project_root / "tools" / "audit_ls_broker_metadata.py"
    spec = importlib.util.spec_from_file_location(
        "audit_ls_broker_metadata",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ls_package_contract(project_root: Path) -> None:
    package = project_root / "strategies" / "ls_volume_delta"
    descriptor = StrategyDescriptor.model_validate(load_yaml(package / "strategy.yaml"))
    run = BacktestRunConfig.model_validate(load_yaml(package / "run.yaml"))

    assert descriptor.strategy_id == "ls_volume_delta"
    assert descriptor.version == "1.0.1"
    assert run.execution_timeframe.value == "M1"
    assert run.strategy.parameters["symbol"] == "US30"
    assert run.strategy.parameters["signal_timeframe"] == "M15"
    assert run.strategy.parameters["delta_source_timeframe"] == "M1"
    assert run.strategy.parameters["primary_reward_risk"] == "2"
    assert run.strategy.parameters["cover_reward_risk"] == "1"
    assert run.risk.max_open_positions == 1
    assert run.risk.allow_pyramiding is False


def test_ls_broker_metadata_semantics(project_root: Path) -> None:
    module = _audit_module(project_root)
    report = module.audit(project_root)
    assert report["ok"], json.dumps(report, ensure_ascii=False, indent=2)
