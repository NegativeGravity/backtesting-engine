from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

SAFE_REVERSE_TAG_KEYS = (
    "strategy",
    "chain_id",
    "trade_date",
    "setup_kind",
    "volume_delta",
    "m2_bar_count",
    "signal_open_time_ns",
    "signal_close_time_ns",
    "signal_open_ticks",
    "signal_high_ticks",
    "signal_low_ticks",
    "signal_close_ticks",
    "hunted_structure_id",
    "hunted_structure_ticks",
    "hunted_structure_time_ns",
    "cover_enabled",
)


class RepairError(RuntimeError):
    pass


def _function_ranges(tree: ast.Module) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ranges.append(
                (
                    node.lineno,
                    getattr(node, "end_lineno", node.lineno),
                    node.name,
                )
            )
    return ranges


def _reverse_function_names(source: str) -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    names: list[str] = []
    for start, end, name in _function_ranges(tree):
        block = "\n".join(lines[start - 1 : end])
        if "stop_and_reverse" in block and "broker_generated" in block:
            names.append(name)
    return sorted(set(names))


def _safe_key_literal() -> str:
    rendered = ", ".join(repr(key) for key in SAFE_REVERSE_TAG_KEYS)
    return "{" + rendered + "}"


def repair_simulator(source: str) -> tuple[str, list[str]]:
    ast.parse(source)
    notes: list[str] = []
    reverse_functions = _reverse_function_names(source)
    if not reverse_functions:
        raise RepairError("Could not find the broker stop-and-reverse order-generation path")

    original = source
    source_pattern = re.compile(
        r"for key in \{\s*['\"]strategy['\"]\s*,\s*"
        r"['\"]chain_id['\"]\s*,\s*['\"]trade_date['\"]\s*\}:\s*\n"
        r"(?P<indent>\s*)if key in entry_order\.request\.tags:\s*\n"
        r"(?P=indent)\s+(?P<target>\w+)\[key\]\s*=\s*"
        r"entry_order\.request\.tags\[key\]",
        flags=re.MULTILINE,
    )

    def replace_known_loop(match: re.Match[str]) -> str:
        indent = match.group("indent")
        target = match.group("target")
        return (
            f"for key in {_safe_key_literal()}:\n"
            f"{indent}if key in position.entry_tags:\n"
            f"{indent}    {target}.setdefault(key, position.entry_tags[key])"
        )

    source, replacements = source_pattern.subn(replace_known_loop, source)
    if replacements:
        notes.append(
            "Replaced reverse metadata source entry_order.request.tags with "
            "position.entry_tags and expanded the non-recursive safe allowlist"
        )

    if "entry_order.request.tags" in source:
        reverse_lines = source.splitlines()
        tree = ast.parse(source)
        for start, end, name in _function_ranges(tree):
            if name not in reverse_functions:
                continue
            block = "\n".join(reverse_lines[start - 1 : end])
            if "entry_order.request.tags" in block:
                updated = block.replace(
                    "entry_order.request.tags",
                    "position.entry_tags",
                )
                source = source.replace(block, updated, 1)
                notes.append(
                    f"Changed reverse tag source in function {name} to position.entry_tags"
                )

    if "position.entry_tags" not in source:
        notes.append(
            "Broker enrichment pattern was not present; Strategy runtime "
            "recovery remains authoritative"
        )

    ast.parse(source)
    if source == original:
        notes.append("Simulator already compatible or no safe textual repair needed")
    return source, notes


def audit_simulator(source: str) -> dict[str, object]:
    tree = ast.parse(source)
    reverse_functions = _reverse_function_names(source)
    reverse_blocks: list[str] = []
    lines = source.splitlines()
    for start, end, name in _function_ranges(tree):
        if name in reverse_functions:
            reverse_blocks.append("\n".join(lines[start - 1 : end]))
    combined = "\n".join(reverse_blocks)
    safe_keys = {
        key: (repr(key) in combined or f'"{key}"' in combined)
        for key in ("strategy", "chain_id", "trade_date")
    }
    return {
        "reverse_functions": reverse_functions,
        "uses_position_entry_tags": "position.entry_tags" in combined,
        "required_identity_keys": safe_keys,
        "recursive_control_tags_copied": any(
            key in combined
            for key in (
                "vex.stop_and_reverse.enabled",
                "vex.stop_and_reverse.stop_ticks",
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    simulator = root / "src/vex_broker/simulator.py"
    if not simulator.is_file():
        raise RepairError(f"Simulator not found: {simulator}")

    original = simulator.read_text(encoding="utf-8")
    repaired, notes = repair_simulator(original)
    changed = repaired != original
    backup = None
    if changed:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = root / ".backup" / f"ls-cover-metadata-{timestamp}" / "src/vex_broker/simulator.py"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(simulator, backup)
        temporary = simulator.with_suffix(".py.ls-cover.tmp")
        temporary.write_text(repaired, encoding="utf-8")
        ast.parse(repaired, filename=str(simulator))
        temporary.replace(simulator)

    strategy = root / "strategies/ls_volume_delta/strategy.py"
    strategy_source = strategy.read_text(encoding="utf-8")
    strategy_checks = {
        "reverse_normalizer": "_normalized_entry_tags" in strategy_source,
        "broker_chain_fallback": "resolve_reverse_chain_id" in strategy_source,
        "single_active_chain_fallback": "len(known) == 1"
        in (root / "strategies/ls_volume_delta/core.py").read_text(encoding="utf-8"),
        "signal_metadata_reconstruction": "_signal_metadata_tags" in strategy_source,
    }
    audit = audit_simulator(simulator.read_text(encoding="utf-8"))
    strategy_ok = all(strategy_checks.values())
    broker_identity_ok = bool(audit["uses_position_entry_tags"]) and all(
        audit["required_identity_keys"].values()
    )
    result = {
        "changed": changed,
        "backup": None if backup is None else str(backup),
        "notes": notes,
        "broker_audit": audit,
        "strategy_checks": strategy_checks,
        "strategy_runtime_recovery_ok": strategy_ok,
        "broker_identity_enrichment_ok": broker_identity_ok,
        "overall_ok": strategy_ok,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report is not None:
        report_path = args.report
        if not report_path.is_absolute():
            report_path = root / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if strategy_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RepairError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
