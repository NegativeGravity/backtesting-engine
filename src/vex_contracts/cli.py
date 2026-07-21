import argparse
import json
from pathlib import Path
from typing import Any

from vex_contracts.registry import contract_kinds, validate_contract
from vex_contracts.schema_export import export_schemas
from vex_contracts.serialization import canonical_data, fingerprint, load_json, load_yaml


def _load_path(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return load_yaml(path)
    if suffix == ".json":
        return load_json(path)
    raise ValueError("contract files must use .json, .yaml, or .yml")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--kind", required=True, choices=contract_kinds())
    validate_parser.add_argument("--path", required=True, type=Path)

    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("--kind", required=True, choices=contract_kinds())
    fingerprint_parser.add_argument("--path", required=True, type=Path)

    schema_parser = subparsers.add_parser("export-schemas")
    schema_parser.add_argument("--output", required=True, type=Path)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "validate":
        model = validate_contract(args.kind, _load_path(args.path))
        print(json.dumps(canonical_data(model), ensure_ascii=False, indent=2, sort_keys=True))
        return

    if args.command == "fingerprint":
        model = validate_contract(args.kind, _load_path(args.path))
        print(fingerprint(model))
        return

    if args.command == "export-schemas":
        for path in export_schemas(args.output):
            print(path.as_posix())
        return

    parser.error("unsupported command")
