from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class RepairError(RuntimeError):
    pass


@dataclass(slots=True)
class Change:
    path: Path
    before: str
    after: str
    reason: str


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def class_block(text: str, name: str) -> tuple[int, int]:
    match = re.search(rf"^class {re.escape(name)}\b.*?:\n", text, re.MULTILINE)
    if not match:
        raise RepairError(f"class {name} not found")
    start = match.start()
    next_match = re.search(r"^class \w+\b.*?:\n", text[match.end():], re.MULTILINE)
    end = len(text) if next_match is None else match.end() + next_match.start()
    return start, end


def call_block(
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
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
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
        raise RepairError(
            f"ambiguous {constructor} call for predicate {predicate!r}"
        )
    return candidates[0] if candidates else None


def insert_call_fields(
    text: str,
    constructor: str,
    *,
    predicate: str,
    anchor: str,
    fields: str,
) -> tuple[str, bool]:
    located = call_block(
        text,
        constructor,
        predicate=predicate,
        anchor=anchor,
    )
    if located is None:
        return text, False
    start, end = located
    block = text[start:end]
    if "entry_tags=" in block:
        return text, False
    block = block.replace(anchor, anchor + fields, 1)
    return text[:start] + block + text[end:], True


def patch_models(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line == "from dataclasses import dataclass":
        text = text.replace(
            "from dataclasses import dataclass\n",
            "from dataclasses import dataclass, field\n",
            1,
        )
        notes.append("imported dataclasses.field")
    elif "from dataclasses import" in text and "field" not in first_line:
        text = re.sub(
            r"^from dataclasses import ([^\n]+)$",
            lambda match: (
                match.group(0)
                if "field" in match.group(1)
                else f"from dataclasses import {match.group(1)}, field"
            ),
            text,
            count=1,
            flags=re.MULTILINE,
        )
        notes.append("imported dataclasses.field")

    start, end = class_block(text, "PositionState")
    block = text[start:end]
    if "entry_tags:" not in block:
        anchor = "    entry_order_id: str\n"
        if anchor not in block:
            raise RepairError("PositionState.entry_order_id anchor is missing")
        block = block.replace(
            anchor,
            anchor
            + '    entry_client_order_id: str = ""\n'
            + "    entry_tags: dict[str, str] = field(default_factory=dict)\n",
            1,
        )
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
        notes.append("restored PositionState entry metadata")
    return text, notes


def patch_simulator(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    text, changed = insert_call_fields(
        text,
        "PositionState",
        predicate="opened_time_ns=cast(int, order.terminal_time_ns)",
        anchor="            entry_order_id=order.order_id,\n",
        fields=(
            "            entry_client_order_id=request.client_order_id,\n"
            "            entry_tags=dict(request.tags),\n"
        ),
    )
    if changed:
        notes.append("propagated request metadata into PositionState")

    text, changed = insert_call_fields(
        text,
        "Trade",
        predicate="trade_id=self._ids.next",
        anchor="            exit_price_ticks=Decimal(exit_price_ticks),\n",
        fields=(
            "            entry_order_id=position.entry_order_id,\n"
            "            entry_client_order_id=position.entry_client_order_id,\n"
            "            entry_tags=dict(position.entry_tags),\n"
        ),
    )
    if changed:
        notes.append("propagated entry metadata into Trade")

    for predicate, description in (
        ("status=PositionStatus.CLOSED", "closed Position"),
        ("status=PositionStatus.OPEN", "open Position"),
    ):
        text, changed = insert_call_fields(
            text,
            "Position",
            predicate=predicate,
            anchor="            opened_time_ns=position.opened_time_ns,\n",
            fields=(
                "            entry_order_id=position.entry_order_id,\n"
                "            entry_client_order_id=position.entry_client_order_id,\n"
                "            entry_tags=dict(position.entry_tags),\n"
            ),
        )
        if changed:
            notes.append(f"propagated metadata into {description}")

    state_anchor = "            opened_time_ns=state.opened_time_ns,\n"
    if "entry_tags=dict(state.entry_tags)" not in text:
        located = call_block(
            text,
            "Position",
            predicate="average_entry_price_ticks=state.average_entry_price_ticks",
            anchor=state_anchor,
        )
        if located is not None:
            start, end = located
            block = text[start:end].replace(
                state_anchor,
                state_anchor
                + "            entry_order_id=state.entry_order_id,\n"
                + "            entry_client_order_id=state.entry_client_order_id,\n"
                + "            entry_tags=dict(state.entry_tags),\n",
                1,
            )
            text = text[:start] + block + text[end:]
            notes.append("propagated PositionState metadata into Position contract")

    required = (
        "entry_client_order_id=request.client_order_id",
        "entry_tags=dict(request.tags)",
        "entry_order_id=position.entry_order_id",
        "entry_client_order_id=position.entry_client_order_id",
        "entry_tags=dict(position.entry_tags)",
        "entry_order_id=state.entry_order_id",
        "entry_client_order_id=state.entry_client_order_id",
        "entry_tags=dict(state.entry_tags)",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise RepairError(
            "simulator metadata propagation remains incomplete: "
            + ", ".join(missing)
        )

    if "broker_generated" in text and "stop_and_reverse" in text:
        reverse_required = (
            '"chain_id"',
            '"trade_date"',
            '"leg"',
        )
        if not all(token in text for token in reverse_required):
            raise RepairError(
                "stop-and-reverse path does not preserve chain identity"
            )
    return text, notes


def patch_strategy(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    if "allow_overlapping_daily_chains: bool" not in text:
        anchor = "    strict_box_validation: bool = True\n"
        if anchor not in text:
            raise RepairError("YJ parameter insertion anchor is missing")
        text = text.replace(
            anchor,
            anchor + "    allow_overlapping_daily_chains: bool = True\n",
            1,
        )
        notes.append("added allow_overlapping_daily_chains parameter")
    if "tags = position.entry_tags" in text:
        text = text.replace(
            "        tags = position.entry_tags\n",
            '        tags = getattr(position, "entry_tags", {}) or {}\n',
            1,
        )
        notes.append("added compatibility-safe entry_tags read")
    if "_awaiting_reversal: tuple[date, str] | None" in text:
        raise RepairError(
            "strategy still contains global reversal state; replace it with "
            "the complete strategy.py included in this kit"
        )
    return text, notes


def interface_block(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(rf"^export interface {re.escape(name)}\s*\{{", text, re.MULTILINE)
    if match is None:
        return None
    start = match.start()
    cursor = match.end()
    depth = 1
    while cursor < len(text):
        char = text[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, cursor + 1
        cursor += 1
    raise RepairError(f"unterminated TypeScript interface: {name}")


def patch_frontend_types(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    located = interface_block(text, "PositionRecord")
    if located is not None:
        start, end = located
        block = text[start:end]
        if "entry_tags?" not in block:
            anchor = "  opened_time_ns: number;\n"
            if anchor not in block:
                raise RepairError("PositionRecord.opened_time_ns anchor is missing")
            block = block.replace(
                anchor,
                anchor
                + "  entry_order_id?: string | null;\n"
                + "  entry_client_order_id?: string | null;\n"
                + "  entry_tags?: Record<string, string>;\n",
                1,
            )
            text = text[:start] + block + text[end:]
            notes.append("restored PositionRecord entry metadata")

    located = interface_block(text, "TradeRecord")
    if located is not None:
        start, end = located
        block = text[start:end]
        if "entry_tags?" not in block:
            anchors = (
                "  exit_price_ticks: string;\n",
                "  exit_price_ticks: number;\n",
            )
            anchor = next((candidate for candidate in anchors if candidate in block), None)
            if anchor is None:
                raise RepairError("TradeRecord.exit_price_ticks anchor is missing")
            block = block.replace(
                anchor,
                anchor
                + "  entry_order_id?: string | null;\n"
                + "  entry_client_order_id?: string | null;\n"
                + "  entry_tags?: Record<string, string>;\n",
                1,
            )
            text = text[:start] + block + text[end:]
            notes.append("restored TradeRecord entry metadata")
    return text, notes

def patch_trading_chart(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    if "bootstrap.bars.length > 0" not in text:
        history_bootstrap = (
            "    liveBarBufferRef.current.replace(bootstrap.bars);\n"
            "    barBufferRef.current.replace(bootstrap.bars);\n"
        )
        if history_bootstrap in text:
            text = text.replace(
                history_bootstrap,
                "    if (bootstrap.bars.length > 0) {\n"
                "      liveBarBufferRef.current.replace(bootstrap.bars);\n"
                "      barBufferRef.current.replace(bootstrap.bars);\n"
                "    }\n",
                1,
            )
            notes.append("prevented empty bootstrap from clearing candle buffers")
        else:
            simple_bootstrap = "    barBufferRef.current.replace(bootstrap.bars);\n"
            if simple_bootstrap in text:
                text = text.replace(
                    simple_bootstrap,
                    "    if (bootstrap.bars.length > 0) {\n"
                    "      barBufferRef.current.replace(bootstrap.bars);\n"
                    "    }\n",
                    1,
                )
                notes.append("prevented empty bootstrap from clearing candles")

    function_match = re.search(
        r"  const applyResetFrame = useCallback\(\(frame: ReplayFrame\) => \{",
        text,
    )
    if function_match:
        start = function_match.start()
        next_marker = text.find("\n  const ", function_match.end())
        end = len(text) if next_marker < 0 else next_marker
        block = text[start:end]
        if "frame.bars.length > 0" not in block:
            history_reset = (
                "    liveBarBufferRef.current.replace(frame.bars);\n"
                "    barBufferRef.current.replace(frame.bars);\n"
            )
            if history_reset in block:
                block = block.replace(
                    history_reset,
                    "    if (frame.bars.length > 0) {\n"
                    "      liveBarBufferRef.current.replace(frame.bars);\n"
                    "      barBufferRef.current.replace(frame.bars);\n"
                    "    }\n",
                    1,
                )
                notes.append(
                    "prevented empty Turbo reset from clearing candle buffers"
                )
            elif "    barBufferRef.current.replace(frame.bars);\n" in block:
                block = block.replace(
                    "    barBufferRef.current.replace(frame.bars);\n",
                    "    if (frame.bars.length > 0) {\n"
                    "      barBufferRef.current.replace(frame.bars);\n"
                    "    }\n",
                    1,
                )
                notes.append("prevented empty Turbo reset from clearing candles")
            text = text[:start] + block + text[end:]

    if 'frame_type === "reset"' not in text:
        raise RepairError(
            "TradingChart does not handle reset frames; current frontend is "
            "older than the supported Turbo chart implementation"
        )
    if "bootstrap.bars.length > 0" not in text:
        raise RepairError("empty-bootstrap candle guard was not installed")
    if "frame.bars.length > 0" not in text:
        raise RepairError("empty-reset candle guard was not installed")
    return text, notes

def verify_manager(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    if "_pending_bar_reset" in text:
        if "self._remember_recent_bars(result.bars)" not in text:
            anchor = "            self._timeline.extend(items)\n"
            if anchor not in text:
                raise RepairError(
                    "Turbo manager lacks recent-bar memory and safe insertion anchor"
                )
            text = text.replace(
                anchor,
                anchor + "            self._remember_recent_bars(result.bars)\n",
                1,
            )
            notes.append("restored recent-bar memory before Turbo reset")
        required = (
            "_remember_recent_bars",
            "recent_bars.get(",
            'frame_type = (',
            '"reset"',
        )
        missing = [token for token in required if token not in text]
        if missing:
            raise RepairError(
                "Turbo manager reset pipeline is incomplete: "
                + ", ".join(missing)
            )
    return text, notes


def validate_python(text: str, path: str) -> None:
    try:
        ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise RepairError(f"generated invalid Python for {path}: {exc}") from exc


def collect(root: Path, kit: Path) -> list[Change]:
    changes: list[Change] = []

    replacements = {
        "src/vex_contracts/positions.py": kit / "src/vex_contracts/positions.py",
        "strategies/yj_box_breakout/strategy.py": (
            kit / "strategies/yj_box_breakout/strategy.py"
        ),
        "strategies/yj_box_breakout/run.yaml": (
            kit / "strategies/yj_box_breakout/run.yaml"
        ),
        "strategies/yj_box_breakout/strategy.yaml": (
            kit / "strategies/yj_box_breakout/strategy.yaml"
        ),
        "tests/test_yj_parallel_metadata.py": (
            kit / "tests/test_yj_parallel_metadata.py"
        ),
    }
    for relative, source in replacements.items():
        destination = root / relative
        before = read(destination) if destination.exists() else ""
        after = read(source)
        if before != after:
            changes.append(
                Change(destination, before, after, "complete replacement")
            )

    transforms: tuple[tuple[str, Callable[[str], tuple[str, list[str]]]], ...] = (
        ("src/vex_broker/models.py", patch_models),
        ("src/vex_broker/simulator.py", patch_simulator),
        ("src/vex_orchestrator/manager.py", verify_manager),
        ("apps/dashboard_web/src/lib/types.ts", patch_frontend_types),
        (
            "apps/dashboard_web/src/components/TradingChart.tsx",
            patch_trading_chart,
        ),
    )
    for relative, transform in transforms:
        path = root / relative
        if not path.exists():
            raise RepairError(f"required project file is missing: {relative}")
        before = read(path)
        after, notes = transform(before)
        if relative.endswith(".py"):
            validate_python(after, relative)
        if after != before:
            changes.append(
                Change(path, before, after, "; ".join(notes) or transform.__name__)
            )
    return changes


def apply(root: Path, changes: list[Change]) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / ".backup" / f"yj-parallel-chart-v1.7.3-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    staged: list[tuple[Change, Path]] = []

    for change in changes:
        relative = change.path.relative_to(root)
        backup_path = backup / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if change.path.exists():
            shutil.copy2(change.path, backup_path)
        temp = change.path.with_name(change.path.name + ".vex-hotfix.tmp")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(change.after, encoding="utf-8")
        staged.append((change, temp))

    try:
        for change, temp in staged:
            os.replace(temp, change.path)
    except BaseException:
        for change, _ in staged:
            relative = change.path.relative_to(root)
            backup_path = backup / relative
            if backup_path.exists():
                shutil.copy2(backup_path, change.path)
            elif change.path.exists():
                change.path.unlink()
        raise

    return backup


def run(command: list[str], cwd: Path, *, required: bool = True) -> int:
    print("+", " ".join(command))
    result = subprocess.run(command, cwd=cwd, check=False)
    if required and result.returncode != 0:
        raise RepairError(
            f"command failed with exit code {result.returncode}: "
            + " ".join(command)
        )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--skip-dashboard", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    kit = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").exists():
        raise RepairError(f"not a VEX project root: {root}")

    changes = collect(root, kit)
    print(f"planned changes: {len(changes)}")
    for change in changes:
        print(f" - {change.path.relative_to(root)}: {change.reason}")

    if args.apply:
        backup = apply(root, changes)
        print(f"backup: {backup}")

    if args.verify:
        run(
            [
                "uv",
                "run",
                "ruff",
                "format",
                "src/vex_contracts/positions.py",
                "src/vex_broker/models.py",
                "src/vex_broker/simulator.py",
                "strategies/yj_box_breakout/strategy.py",
                "tests/test_yj_parallel_metadata.py",
            ],
            root,
        )
        run(
            [
                "uv",
                "run",
                "ruff",
                "check",
                "src/vex_contracts/positions.py",
                "src/vex_broker/models.py",
                "src/vex_broker/simulator.py",
                "strategies/yj_box_breakout/strategy.py",
                "tests/test_yj_parallel_metadata.py",
            ],
            root,
        )
        run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "tests/test_yj_parallel_metadata.py",
                "tests/test_yj_strategy.py",
                "tests/test_advanced_orders.py",
            ],
            root,
        )

        schema_script = root / "scripts" / "generate-schemas.py"
        if schema_script.exists():
            run(
                ["uv", "run", "python", str(schema_script.relative_to(root))],
                root,
            )

        if not args.skip_dashboard:
            dashboard = root / "apps" / "dashboard_web"
            run(["npm", "run", "build"], dashboard)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RepairError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
