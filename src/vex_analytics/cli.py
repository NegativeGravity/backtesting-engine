import argparse
import json
from pathlib import Path
from typing import Any

from vex_contracts.serialization import canonical_data
from vex_replay.repository import ReplayRunRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="vex-analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    report_parser.add_argument("--run-id", required=True)
    report_parser.add_argument("--end-time-ns", type=int)
    report_parser.add_argument("--output", type=Path)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    compare_parser.add_argument("--run-id", action="append", default=[])
    compare_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    repository = ReplayRunRepository(args.project_root)
    value: Any
    if args.command == "report":
        value = repository.analytics(args.run_id, args.end_time_ns)
    else:
        value = repository.analytics_comparison(tuple(args.run_id))
    data = canonical_data(value)
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0
