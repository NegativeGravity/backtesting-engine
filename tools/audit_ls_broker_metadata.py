from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class AuditError(RuntimeError):
    pass


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _constructor_calls(source: str, constructor: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node.func) == constructor
    ]


def _keyword_names(call: ast.Call) -> set[str]:
    return {item.arg for item in call.keywords if item.arg is not None}


def _keyword_expression(call: ast.Call, name: str) -> str:
    for item in call.keywords:
        if item.arg == name:
            return ast.unparse(item.value)
    return ""


def _named_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        result: set[str] = set()
        for item in node.elts:
            result.update(_named_targets(item))
        return result
    return set()


def _expression_uses_tag_source(
    node: ast.AST,
    tainted_names: set[str],
) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Attribute) and item.attr in {
            "tags",
            "entry_tags",
        }:
            return True
        if isinstance(item, ast.Name) and item.id in tainted_names:
            return True
    return False


def _tag_flow_report(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    tainted_names: set[str] = set()

    assignments: list[tuple[set[str], ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: set[str] = set()
            for target in node.targets:
                targets.update(_named_targets(target))
            assignments.append((targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append((_named_targets(node.target), node.value))

    changed = True
    while changed:
        changed = False
        for targets, value in assignments:
            if not targets or not _expression_uses_tag_source(
                value,
                tainted_names,
            ):
                continue
            new_names = targets.difference(tainted_names)
            if new_names:
                tainted_names.update(new_names)
                changed = True

    tag_keyword_expressions: list[str] = []
    flowing_keyword_expressions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "tags":
                continue
            expression = ast.unparse(keyword.value)
            tag_keyword_expressions.append(expression)
            if _expression_uses_tag_source(
                keyword.value,
                tainted_names,
            ):
                flowing_keyword_expressions.append(expression)

    return {
        "tainted_names": sorted(tainted_names),
        "tag_keyword_expressions": tag_keyword_expressions,
        "flowing_tag_keyword_expressions": flowing_keyword_expressions,
        "has_generic_tag_flow": bool(flowing_keyword_expressions),
    }


def _runtime_contract_checks(project_root: Path) -> dict[str, bool]:
    probe = r"""
import dataclasses
import json

from vex_broker.models import PositionState
from vex_contracts.positions import Position, Trade


def fields(model):
    pydantic_fields = getattr(model, "model_fields", None)
    if isinstance(pydantic_fields, dict):
        return sorted(pydantic_fields)
    if dataclasses.is_dataclass(model):
        return sorted(field.name for field in dataclasses.fields(model))
    return []


print(
    json.dumps(
        {
            "Position": fields(Position),
            "Trade": fields(Trade),
            "PositionState": fields(PositionState),
        }
    )
)
"""
    environment = os.environ.copy()
    src_path = str(project_root / "src")
    current_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        src_path if not current_pythonpath else src_path + os.pathsep + current_pythonpath
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AuditError(
            "Fresh-process contract probe failed:\n" + completed.stdout + completed.stderr
        )
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise AuditError(
            "Fresh-process contract probe returned invalid JSON: " + completed.stdout
        ) from exc

    required = {
        "entry_order_id",
        "entry_client_order_id",
        "entry_tags",
    }
    return {name: required.issubset(set(fields)) for name, fields in payload.items()}


def _find_class_block(text: str, class_name: str) -> tuple[int, int]:
    match = re.search(
        rf"^class {re.escape(class_name)}\b.*?:\n",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        raise AuditError(f"class {class_name} was not found")
    next_match = re.search(
        r"^class \w+\b.*?:\n",
        text[match.end() :],
        flags=re.MULTILINE,
    )
    end = len(text) if next_match is None else match.end() + next_match.start()
    return match.start(), end


def _call_block(
    text: str,
    constructor: str,
    *,
    predicate: str,
    anchor: str,
) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []
    for match in re.finditer(rf"\b{re.escape(constructor)}\(\n", text):
        start = match.start()
        depth = 0
        end: int | None = None
        for index in range(start, len(text)):
            character = text[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            continue
        block = text[start:end]
        if predicate in block and anchor in block:
            candidates.append((start, end))
    if len(candidates) > 1:
        raise AuditError(f"ambiguous {constructor} call for predicate {predicate!r}")
    return candidates[0] if candidates else None


def _insert_missing_call_fields(
    text: str,
    constructor: str,
    *,
    predicate: str,
    anchor: str,
    fields: tuple[tuple[str, str], ...],
) -> tuple[str, bool]:
    located = _call_block(
        text,
        constructor,
        predicate=predicate,
        anchor=anchor,
    )
    if located is None:
        return text, False

    start, end = located
    block = text[start:end]
    additions = "".join(rendered for keyword, rendered in fields if f"{keyword}=" not in block)
    if not additions:
        return text, False

    block = block.replace(anchor, anchor + additions, 1)
    return text[:start] + block + text[end:], True


def _patch_models(text: str) -> tuple[str, bool]:
    changed = False
    import_match = re.search(
        r"^from dataclasses import ([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    if import_match is None:
        raise AuditError("dataclasses import was not found in broker models")

    imports = [item.strip() for item in import_match.group(1).split(",")]
    if "field" not in imports:
        imports.append("field")
        text = (
            text[: import_match.start()]
            + "from dataclasses import "
            + ", ".join(imports)
            + text[import_match.end() :]
        )
        changed = True

    start, end = _find_class_block(text, "PositionState")
    block = text[start:end]
    anchor = "    entry_order_id: str\n"
    if anchor not in block and "entry_tags:" not in block:
        raise AuditError("PositionState.entry_order_id anchor was not found")

    if "entry_client_order_id:" not in block:
        block = block.replace(
            anchor,
            anchor + '    entry_client_order_id: str = ""\n',
            1,
        )
        changed = True
    if "entry_tags:" not in block:
        insertion_anchor = (
            '    entry_client_order_id: str = ""\n'
            if '    entry_client_order_id: str = ""\n' in block
            else anchor
        )
        block = block.replace(
            insertion_anchor,
            insertion_anchor + "    entry_tags: dict[str, str] = field(default_factory=dict)\n",
            1,
        )
        changed = True

    if changed:
        block = block.replace(
            "    stop_loss_ticks: int | None\n",
            "    stop_loss_ticks: int | None = None\n",
            1,
        )
        block = block.replace(
            "    take_profit_ticks: int | None\n",
            "    take_profit_ticks: int | None = None\n",
            1,
        )
        text = text[:start] + block + text[end:]
    return text, changed


def _patch_simulator(text: str) -> tuple[str, bool]:
    changed = False
    operations = (
        (
            "PositionState",
            "opened_time_ns=cast(int, order.terminal_time_ns)",
            "            entry_order_id=order.order_id,\n",
            (
                (
                    "entry_client_order_id",
                    "            entry_client_order_id=request.client_order_id,\n",
                ),
                (
                    "entry_tags",
                    "            entry_tags=dict(request.tags),\n",
                ),
            ),
        ),
        (
            "Trade",
            "trade_id=self._ids.next",
            "            exit_price_ticks=Decimal(exit_price_ticks),\n",
            (
                (
                    "entry_order_id",
                    "            entry_order_id=position.entry_order_id,\n",
                ),
                (
                    "entry_client_order_id",
                    "            entry_client_order_id=position.entry_client_order_id,\n",
                ),
                (
                    "entry_tags",
                    "            entry_tags=dict(position.entry_tags),\n",
                ),
            ),
        ),
        (
            "Position",
            "status=PositionStatus.CLOSED",
            "            opened_time_ns=position.opened_time_ns,\n",
            (
                (
                    "entry_order_id",
                    "            entry_order_id=position.entry_order_id,\n",
                ),
                (
                    "entry_client_order_id",
                    "            entry_client_order_id=position.entry_client_order_id,\n",
                ),
                (
                    "entry_tags",
                    "            entry_tags=dict(position.entry_tags),\n",
                ),
            ),
        ),
        (
            "Position",
            "status=PositionStatus.OPEN",
            "            opened_time_ns=position.opened_time_ns,\n",
            (
                (
                    "entry_order_id",
                    "            entry_order_id=position.entry_order_id,\n",
                ),
                (
                    "entry_client_order_id",
                    "            entry_client_order_id=position.entry_client_order_id,\n",
                ),
                (
                    "entry_tags",
                    "            entry_tags=dict(position.entry_tags),\n",
                ),
            ),
        ),
        (
            "Position",
            "average_entry_price_ticks=state.average_entry_price_ticks",
            "            opened_time_ns=state.opened_time_ns,\n",
            (
                (
                    "entry_order_id",
                    "            entry_order_id=state.entry_order_id,\n",
                ),
                (
                    "entry_client_order_id",
                    "            entry_client_order_id=state.entry_client_order_id,\n",
                ),
                (
                    "entry_tags",
                    "            entry_tags=dict(state.entry_tags),\n",
                ),
            ),
        ),
    )

    for constructor, predicate, anchor, fields in operations:
        text, operation_changed = _insert_missing_call_fields(
            text,
            constructor,
            predicate=predicate,
            anchor=anchor,
            fields=fields,
        )
        changed = changed or operation_changed
    return text, changed


def _write_atomic_with_backup(
    project_root: Path,
    path: Path,
    content: str,
    backup_root: Path,
) -> None:
    relative = path.relative_to(project_root)
    backup = backup_root / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    temporary = path.with_name(path.name + ".ls-final.tmp")
    temporary.write_text(content, encoding="utf-8")
    ast.parse(content, filename=str(path))
    os.replace(temporary, path)


def audit(project_root: Path) -> dict[str, Any]:
    simulator_path = project_root / "src/vex_broker/simulator.py"
    advanced_path = project_root / "src/vex_broker/advanced_orders.py"
    simulator_source = simulator_path.read_text(encoding="utf-8")
    advanced_source = advanced_path.read_text(encoding="utf-8") if advanced_path.exists() else ""
    combined_source = simulator_source + "\n" + advanced_source

    contract_checks = _runtime_contract_checks(project_root)

    constructor_details: dict[str, list[dict[str, str]]] = {}
    for constructor in ("PositionState", "Position", "Trade"):
        candidates: list[dict[str, str]] = []
        for call in _constructor_calls(simulator_source, constructor):
            names = _keyword_names(call)
            if "entry_tags" not in names:
                continue
            candidates.append(
                {
                    "entry_order_id": _keyword_expression(
                        call,
                        "entry_order_id",
                    ),
                    "entry_client_order_id": _keyword_expression(
                        call,
                        "entry_client_order_id",
                    ),
                    "entry_tags": _keyword_expression(call, "entry_tags"),
                }
            )
        constructor_details[constructor] = candidates

    position_expressions = [item["entry_tags"] for item in constructor_details["Position"]]
    constructor_checks = {
        "PositionState": any(
            item["entry_tags"] and item["entry_client_order_id"]
            for item in constructor_details["PositionState"]
        ),
        "Trade": any(
            "position.entry_tags" in item["entry_tags"] for item in constructor_details["Trade"]
        ),
        "Position": (
            any("position.entry_tags" in expression for expression in position_expressions)
            and any("state.entry_tags" in expression for expression in position_expressions)
        ),
    }

    tag_flow = _tag_flow_report(combined_source)
    semantic_source_checks = {
        "order_tags_consumed": (
            "request.tags" in simulator_source or "order.request.tags" in simulator_source
        ),
        "position_tags_forwarded": (
            "position.entry_tags" in simulator_source and "state.entry_tags" in simulator_source
        ),
        "stop_and_reverse_available": ("stop_and_reverse" in combined_source),
        "reverse_order_marked": "broker_generated" in combined_source,
        "reverse_leg_identity_available": (
            '"leg"' in combined_source or "'leg'" in combined_source
        ),
        "generic_reverse_tag_flow": tag_flow["has_generic_tag_flow"],
    }

    ok = (
        all(contract_checks.values())
        and all(constructor_checks.values())
        and all(semantic_source_checks.values())
    )
    return {
        "ok": ok,
        "contract_checks": contract_checks,
        "constructor_checks": constructor_checks,
        "constructor_details": constructor_details,
        "semantic_source_checks": semantic_source_checks,
        "tag_flow": tag_flow,
    }


def repair(project_root: Path) -> dict[str, Any]:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = project_root / ".backup" / f"ls-final-metadata-{timestamp}"
    changed_files: list[str] = []

    models_path = project_root / "src/vex_broker/models.py"
    models_source = models_path.read_text(encoding="utf-8")
    patched_models, models_changed = _patch_models(models_source)
    if models_changed:
        _write_atomic_with_backup(
            project_root,
            models_path,
            patched_models,
            backup_root,
        )
        changed_files.append(str(models_path.relative_to(project_root)))

    simulator_path = project_root / "src/vex_broker/simulator.py"
    simulator_source = simulator_path.read_text(encoding="utf-8")
    patched_simulator, simulator_changed = _patch_simulator(simulator_source)
    if simulator_changed:
        _write_atomic_with_backup(
            project_root,
            simulator_path,
            patched_simulator,
            backup_root,
        )
        changed_files.append(str(simulator_path.relative_to(project_root)))

    return {
        "backup_root": str(backup_root),
        "changed_files": changed_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not (project_root / "pyproject.toml").exists():
        raise AuditError(f"Not a VEX project root: {project_root}")

    before = audit(project_root)
    repair_report: dict[str, Any] | None = None
    if args.repair and not before["ok"]:
        repair_report = repair(project_root)

    after = audit(project_root)
    result = {
        "before": before,
        "repair": repair_report,
        "after": after,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)

    if args.report is not None:
        report_path = args.report
        if not report_path.is_absolute():
            report_path = project_root / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")

    return 0 if after["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, OSError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
