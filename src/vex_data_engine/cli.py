import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from vex_contracts.data_engine import DataEngineConfig
from vex_contracts.dataset import DatasetManifest
from vex_contracts.serialization import canonical_data, dump_yaml, load_json, load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.discovery import discover_mt5_files
from vex_data_engine.engine import Mt5DataEngine
from vex_data_engine.manifest_builder import build_manifest


def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    data: Any = load_json(path) if path.suffix.lower() == ".json" else load_yaml(path)
    return model.model_validate(data)


def _parse_time_ns(value: str | None) -> int | None:
    if value is None:
        return None
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000_000)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--root", type=Path, required=True)
    discover.add_argument("--recursive", action="store_true")

    manifest = subparsers.add_parser("build-manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--repository-root", type=Path, default=Path.cwd())
    manifest.add_argument("--dataset-id", required=True)
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--name", required=True)
    manifest.add_argument("--source-timezone", required=True)
    manifest.add_argument("--output", type=Path, required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    import_parser.add_argument("--manifest", type=Path, required=True)
    import_parser.add_argument("--symbol-profile", type=Path, action="append", required=True)
    import_parser.add_argument("--config", type=Path)

    query = subparsers.add_parser("query")
    query.add_argument("--project-root", type=Path, default=Path.cwd())
    query.add_argument("--report", type=Path, required=True)
    query.add_argument("--symbol", required=True)
    query.add_argument("--timeframe", type=Timeframe, required=True)
    query.add_argument("--start")
    query.add_argument("--end")
    query.add_argument("--limit", type=int, default=100)
    query.add_argument("--include-incomplete", action="store_true")

    sync = subparsers.add_parser("sync-preview")
    sync.add_argument("--project-root", type=Path, default=Path.cwd())
    sync.add_argument("--report", type=Path, required=True)
    sync.add_argument("--subscription", action="append", required=True)
    sync.add_argument("--start")
    sync.add_argument("--end")
    sync.add_argument("--limit", type=int, default=20)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "discover":
        result = [
            {
                "path": item.path.as_posix(),
                "symbol": item.symbol,
                "timeframe": item.timeframe.value,
                "declared_start_local": item.declared_start_local.isoformat(),
                "declared_end_local": item.declared_end_local.isoformat(),
                "canonical_name": item.canonical_name,
            }
            for item in discover_mt5_files(args.root, args.recursive)
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "build-manifest":
        result = build_manifest(
            args.root,
            args.dataset_id,
            args.version,
            args.name,
            args.source_timezone,
            args.repository_root,
        )
        dump_yaml(result, args.output)
        print(args.output.as_posix())
        return

    if args.command == "import":
        manifest = _load_model(args.manifest, DatasetManifest)
        profiles = [
            _load_model(profile_path, SymbolProfile) for profile_path in args.symbol_profile
        ]
        config = (
            _load_model(args.config, DataEngineConfig)
            if args.config is not None
            else DataEngineConfig()
        )
        outcome = Mt5DataEngine(args.project_root).import_dataset(
            manifest,
            {profile.symbol: profile for profile in profiles},
            config,
        )
        print(json.dumps(canonical_data(outcome.report), ensure_ascii=False, indent=2))
        print(outcome.report_path.as_posix())
        print(outcome.resolved_manifest_path.as_posix())
        return

    if args.command == "query":
        from vex_data_engine.catalog import ParquetBarStore

        store = ParquetBarStore.from_report_path(args.project_root, args.report)
        frame = store.load(
            args.symbol,
            args.timeframe,
            _parse_time_ns(args.start),
            _parse_time_ns(args.end),
            not args.include_incomplete,
            args.limit,
        )
        print(json.dumps(frame.to_dicts(), ensure_ascii=False, indent=2))
        return

    if args.command == "sync-preview":
        from vex_data_engine.catalog import ParquetBarStore

        subscriptions = tuple(
            (symbol.upper(), Timeframe(timeframe.upper()))
            for value in args.subscription
            for symbol, timeframe in [value.split(":", maxsplit=1)]
        )
        store = ParquetBarStore.from_report_path(args.project_root, args.report)
        batches = []
        for index, batch in enumerate(
            store.iter_close_batches(
                subscriptions,
                _parse_time_ns(args.start),
                _parse_time_ns(args.end),
            )
        ):
            if index >= args.limit:
                break
            batches.append({"close_time_ns": batch.close_time_ns, "bars": batch.bars})
        print(json.dumps(batches, ensure_ascii=False, indent=2))
        return

    parser.error("unsupported command")
