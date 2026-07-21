import argparse
import json
from multiprocessing import freeze_support
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import dump_json, load_json, load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_data_engine.catalog import ParquetBarStore
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.runner import StrategyBacktestRunner


def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    data: Any = load_json(path) if path.suffix.lower() == ".json" else load_yaml(path)
    return model.model_validate(data)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-strategy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--project-root", type=Path, default=Path.cwd())
    run.add_argument(
        "--run-config",
        type=Path,
        default=Path("examples/configs/run_strategy_smoke.yaml"),
    )
    run.add_argument(
        "--strategy-descriptor",
        type=Path,
        default=Path("examples/configs/strategy_sdk_smoke.yaml"),
    )
    run.add_argument(
        "--runtime-config",
        type=Path,
        default=Path("examples/configs/strategy_runtime.yaml"),
    )
    run.add_argument(
        "--symbol-profile",
        type=Path,
        action="append",
    )
    run.add_argument(
        "--import-report",
        type=Path,
        default=Path("data/cache/xauusd_mt5_2025_2026/2/import-report.json"),
    )
    run.add_argument("--max-close-batches", type=int, default=250)
    run.add_argument(
        "--output-directory",
        type=Path,
        default=Path("data/cache/strategy-smoke"),
    )
    run.add_argument(
        "--report-output",
        type=Path,
        default=Path("data/cache/strategy-smoke-report.json"),
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    run_config = _load_model(root / args.run_config, BacktestRunConfig)
    descriptor = _load_model(root / args.strategy_descriptor, StrategyDescriptor)
    runtime_config = _load_model(root / args.runtime_config, StrategyRuntimeConfig)
    profile_paths = args.symbol_profile or [Path("examples/configs/symbol_xauusd.yaml")]
    profiles = [_load_model(root / path, SymbolProfile) for path in profile_paths]
    store = ParquetBarStore.from_report_path(root, root / args.import_report)
    recorder = StrategyOutputRecorder(root / args.output_directory)
    runner = StrategyBacktestRunner(
        run_config,
        descriptor,
        runtime_config,
        {profile.symbol: profile for profile in profiles},
        store,
        recorder,
    )
    report = runner.run(args.max_close_batches)
    dump_json(report, root / args.report_output)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def main() -> int:
    freeze_support()
    args = _parser().parse_args()
    if args.command == "run":
        return _run(args)
    raise ValueError(f"unsupported command: {args.command}")
