from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)
if PROJECT_ROOT_TEXT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_TEXT)

STRATEGY_PATH = (
    PROJECT_ROOT
    / "strategies"
    / "ls_volume_delta"
    / "strategy.py"
)

SCALAR_TYPES = (str, int, float, bool)
CONTAINER_NODES = (
    ast.List,
    ast.Dict,
    ast.Set,
    ast.Tuple,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
)
CONTAINER_CALLS = {"sorted", "list", "dict", "set", "tuple"}


def _is_context_log_call(node: ast.Call) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr in {"debug", "info", "warning", "error", "critical"}
        and isinstance(function.value, ast.Attribute)
        and function.value.attr == "log"
    )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_recovery_source_keys_are_scalar() -> None:
    module = importlib.import_module(
        "strategies.ls_volume_delta.strategy"
    )
    strategy_type = module.LsVolumeDeltaStrategy

    raw_tags = {
        "broker_generated": "stop_and_reverse",
        "leg": "2",
        "vex.stop_and_reverse.chain_id": "ls-2026-01-05-00001",
    }
    fields = {
        "source_keys": strategy_type._log_source_keys(raw_tags),
        "source_key_count": len(raw_tags),
    }

    assert fields["source_keys"] == (
        "broker_generated,leg,vex.stop_and_reverse.chain_id"
    )
    assert fields["source_key_count"] == 3
    assert all(
        isinstance(value, SCALAR_TYPES)
        for value in fields.values()
    )


def test_risk_status_log_fields_are_scalar() -> None:
    core = importlib.import_module(
        "strategies.ls_volume_delta.core"
    )
    governor = core.RiskGovernor(
        maximum_positions_per_day=5,
        maximum_primary_take_profits_per_day=2,
        daily_loss_limit_r=core.Decimal("-4"),
        monthly_loss_limit_r=core.Decimal("-8"),
        monthly_pause_target_r=core.Decimal("6"),
        monthly_profit_target_r=core.Decimal("8"),
        pause_loss_threshold_r=core.Decimal("-7"),
    )
    assert all(
        isinstance(value, SCALAR_TYPES)
        for value in governor.status().values()
    )


def test_context_log_keywords_do_not_build_containers() -> None:
    tree = ast.parse(
        STRATEGY_PATH.read_text(encoding="utf-8"),
        filename=str(STRATEGY_PATH),
    )
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_context_log_call(node):
            continue
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            value = keyword.value
            if isinstance(value, CONTAINER_NODES):
                violations.append(
                    f"line {value.lineno}: {keyword.arg}="
                    f"{ast.unparse(value)}"
                )
                continue
            if isinstance(value, ast.Call):
                name = _call_name(value.func)
                if name in CONTAINER_CALLS:
                    violations.append(
                        f"line {value.lineno}: {keyword.arg}="
                        f"{ast.unparse(value)}"
                    )

    assert not violations, "\n".join(violations)


def test_recovery_logs_use_scalar_helper() -> None:
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    assert source.count(
        "source_keys=self._log_source_keys(raw_tags)"
    ) == 2
    assert source.count("source_key_count=len(raw_tags)") == 2
    assert "source_keys=sorted(raw_tags)" not in source
