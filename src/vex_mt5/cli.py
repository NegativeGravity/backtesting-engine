from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from vex_contracts.mt5 import (
    Mt5CompatibilitySnapshot,
    Mt5ValidationConfig,
)
from vex_contracts.mt5_bridge import Mt5BridgeConfig
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import dump_json, dump_yaml, load_json, load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_mt5.collector import collect_snapshot
from vex_mt5.profile import profile_from_snapshot
from vex_mt5.validator import validate_snapshot


def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    data: Any = load_json(path) if path.suffix.lower() == ".json" else load_yaml(path)
    return model.model_validate(data)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-mt5")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--project-root", type=Path, default=Path.cwd())
    collect.add_argument("--config", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    profile = subparsers.add_parser("profile")
    profile.add_argument("--project-root", type=Path, default=Path.cwd())
    profile.add_argument("--snapshot", type=Path, required=True)
    profile.add_argument("--symbol", required=True)
    profile.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--project-root", type=Path, default=Path.cwd())
    validate.add_argument("--config", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    return parser


def _collect(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    config = _load_model(root / args.config, Mt5BridgeConfig)
    snapshot = collect_snapshot(config)
    dump_json(snapshot, root / args.output)
    print(json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _profile(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    snapshot = _load_model(root / args.snapshot, Mt5CompatibilitySnapshot)
    symbol = next((item for item in snapshot.symbols if item.symbol == args.symbol), None)
    if symbol is None:
        raise ValueError(f"symbol not present in snapshot: {args.symbol}")
    profile = profile_from_snapshot(symbol)
    dump_yaml(profile, root / args.output)
    print(json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _validate(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    config = _load_model(root / args.config, Mt5ValidationConfig)
    snapshot = _load_model(root / config.snapshot_path, Mt5CompatibilitySnapshot)
    profiles = tuple(
        _load_model(root / path, SymbolProfile) for path in config.symbol_profile_paths
    )
    run_config = (
        None
        if config.run_config_path is None
        else _load_model(root / config.run_config_path, BacktestRunConfig)
    )
    report = validate_snapshot(
        snapshot,
        profiles,
        config.tolerance,
        run_config,
        config.fail_on_warning,
    )
    dump_json(report, root / args.output)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if report.compatible else 2


def main() -> int:
    args = _parser().parse_args()
    if args.command == "collect":
        return _collect(args)
    if args.command == "profile":
        return _profile(args)
    if args.command == "validate":
        return _validate(args)
    raise ValueError(f"unsupported command: {args.command}")
