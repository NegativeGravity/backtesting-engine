from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Run with: uv run python scripts/verify-yj-parallel.py"
    ) from exc


REQUIRED_STRATEGY_TOKENS = (
    "allow_overlapping_daily_chains",
    "if not config.allow_overlapping_daily_chains",
    "_position_identity",
    "position.entry_tags",
    "STOP_AND_REVERSE_ACCOUNT_BASIS_TAG",
    "EXECUTION_ACCOUNT_BASIS_TAG",
)

REQUIRED_SIMULATOR_TOKENS = (
    "entry_tags=dict(request.tags)",
    "entry_tags=dict(position.entry_tags)",
    'if key in {"strategy", "chain_id", "trade_date"}',
)


def load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected mapping in {path}")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.project_root.resolve()

    package_root = root / "strategies" / "yj_box_breakout"
    run = load_yaml(package_root / "run.yaml")
    descriptor = load_yaml(package_root / "strategy.yaml")
    strategy_source = (package_root / "strategy.py").read_text(encoding="utf-8")
    positions_source = (root / "src" / "vex_contracts" / "positions.py").read_text(encoding="utf-8")
    simulator_source = (root / "src" / "vex_broker" / "simulator.py").read_text(encoding="utf-8")

    parameters = run["strategy"]["parameters"]
    risk = run["risk"]
    account = run["account"]
    defaults = descriptor["default_parameters"]

    require(
        parameters["allow_overlapping_daily_chains"] is True,
        "run.yaml disables overlapping daily chains",
    )
    require(
        defaults["allow_overlapping_daily_chains"] is True,
        "strategy.yaml disables overlapping daily chains",
    )
    require(
        account["position_mode"] == "hedging", "YJ parallel mode requires hedging position mode"
    )
    require(risk["allow_pyramiding"] is True, "YJ parallel mode requires allow_pyramiding=true")
    require(int(risk["max_open_positions"]) >= 2, "max_open_positions must be at least 2")
    require(int(risk["max_symbol_positions"]) >= 2, "max_symbol_positions must be at least 2")

    missing = [token for token in REQUIRED_STRATEGY_TOKENS if token not in strategy_source]
    require(not missing, f"strategy.py lacks parallel-chain support: {missing}")
    require(
        "_awaiting_reversal: tuple[date, str] | None" not in strategy_source,
        "strategy.py still uses one global awaiting-reversal slot",
    )

    for token in ("entry_order_id", "entry_client_order_id", "entry_tags"):
        require(token in positions_source, f"positions.py lacks {token}")

    missing = [token for token in REQUIRED_SIMULATOR_TOKENS if token not in simulator_source]
    require(not missing, f"simulator.py lacks chain metadata propagation: {missing}")

    print("YJ parallel-chain contract: PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"YJ parallel-chain contract: FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
