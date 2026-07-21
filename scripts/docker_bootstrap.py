from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORT_REPORT = PROJECT_ROOT / "data/cache/xauusd_mt5_2025_2026/2/import-report.json"
RUN_ID = "run_xauusd_sma_cross_demo_v1"
REPLAY_MANIFEST = PROJECT_ROOT / f"data/replay/runs/{RUN_ID}/manifest.json"
MT5_REPORT = PROJECT_ROOT / "data/cache/mt5-compatibility-report.json"
BOOTSTRAP_REPORT = PROJECT_ROOT / "data/replay/docker-bootstrap.json"


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], cwd=PROJECT_ROOT, check=True)


def main() -> int:
    force = os.getenv("VEX_FORCE_REBUILD", "0") == "1"
    max_batches = os.getenv("VEX_DEMO_MAX_CLOSE_BATCHES", "5000")
    if force or not IMPORT_REPORT.exists():
        run(
            "-m",
            "vex_data_engine",
            "import",
            "--project-root",
            ".",
            "--manifest",
            "examples/configs/dataset.yaml",
            "--symbol-profile",
            "examples/configs/symbol_xauusd.yaml",
            "--config",
            "examples/configs/data_engine.yaml",
        )
    if force or not REPLAY_MANIFEST.exists():
        run(
            "-m",
            "vex_replay",
            "build",
            "--project-root",
            ".",
            "--run-config",
            "strategies/sma_cross_demo/run.yaml",
            "--strategy-descriptor",
            "strategies/sma_cross_demo/strategy.yaml",
            "--runtime-config",
            "strategies/sma_cross_demo/runtime.yaml",
            "--symbol-profile",
            "examples/configs/symbol_xauusd.yaml",
            "--import-report",
            "data/cache/xauusd_mt5_2025_2026/2/import-report.json",
            "--output-root",
            "data/replay/runs",
            "--max-close-batches",
            max_batches,
            "--snapshot-interval-bars",
            "50",
            "--strategy-source",
            "strategies",
        )
    run(
        "-m",
        "vex_mt5",
        "validate",
        "--project-root",
        ".",
        "--config",
        "examples/configs/mt5_validation.yaml",
        "--output",
        str(MT5_REPORT.relative_to(PROJECT_ROOT)),
    )
    payload = {
        "completed_at": datetime.now(UTC).isoformat(),
        "import_report": str(IMPORT_REPORT.relative_to(PROJECT_ROOT)),
        "replay_manifest": str(REPLAY_MANIFEST.relative_to(PROJECT_ROOT)),
        "mt5_report": str(MT5_REPORT.relative_to(PROJECT_ROOT)),
        "max_close_batches": int(max_batches),
    }
    BOOTSTRAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_REPORT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
