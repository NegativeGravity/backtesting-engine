import argparse
import json
from multiprocessing import freeze_support
from pathlib import Path

from vex_replay.builder import ReplayBundleBuilder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-replay")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--project-root", type=Path, default=Path.cwd())
    build.add_argument(
        "--run-config",
        type=Path,
        default=Path("examples/configs/run_strategy_smoke.yaml"),
    )
    build.add_argument(
        "--strategy-descriptor",
        type=Path,
        default=Path("examples/configs/strategy_sdk_smoke.yaml"),
    )
    build.add_argument(
        "--runtime-config",
        type=Path,
        default=Path("examples/configs/strategy_runtime.yaml"),
    )
    build.add_argument(
        "--symbol-profile",
        type=Path,
        action="append",
    )
    build.add_argument(
        "--import-report",
        type=Path,
        default=Path("data/cache/xauusd_mt5_2025_2026/2/import-report.json"),
    )
    build.add_argument("--output-root", type=Path, default=Path("data/replay/runs"))
    build.add_argument("--max-close-batches", type=int, default=250)
    build.add_argument("--snapshot-interval-bars", type=int, default=25)
    build.add_argument("--strategy-source", type=Path, default=None)
    return parser


def _build(args: argparse.Namespace) -> int:
    profiles = args.symbol_profile or [Path("examples/configs/symbol_xauusd.yaml")]
    builder = ReplayBundleBuilder(
        project_root=args.project_root,
        run_config_path=args.run_config,
        strategy_descriptor_path=args.strategy_descriptor,
        runtime_config_path=args.runtime_config,
        symbol_profile_paths=profiles,
        import_report_path=args.import_report,
        output_root=args.output_root,
        snapshot_interval_bars=args.snapshot_interval_bars,
        strategy_source_path=args.strategy_source,
    )
    result = builder.build(args.max_close_batches)
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def main() -> int:
    freeze_support()
    args = _parser().parse_args()
    if args.command == "build":
        return _build(args)
    raise ValueError(f"unsupported command: {args.command}")
