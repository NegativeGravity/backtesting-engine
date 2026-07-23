from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


M1_STEM = "US30_M1_202501020101_202607222358"
M15_STEM = "US30_M15_202501020100_202607222345"
SYMBOL = "US30"
DATASET_ID = "us30_mt5_ls"
DATASET_VERSION = "1"
PROFILE_ID = "mt5_us30_ls"
PROFILE_VERSION = "1.0.1"


class PreparationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CsvSummary:
    path: Path
    row_count: int
    size_bytes: int
    sha256: str
    first_time: datetime
    last_time: datetime
    digits: int
    nonzero_volume_rows: int
    delimiter: str


def resolve_data_file(data_root: Path, stem: str) -> Path:
    direct_candidates = (
        data_root / stem,
        data_root / f"{stem}.csv",
        data_root / f"{stem}.CSV",
    )
    existing = [path for path in direct_candidates if path.is_file()]
    if not existing:
        existing = [
            path
            for path in data_root.glob(f"{stem}*")
            if path.is_file()
        ]
    unique = list(dict.fromkeys(path.resolve() for path in existing))
    if len(unique) != 1:
        raise PreparationError(
            f"Expected exactly one file for {stem}, found: "
            + ", ".join(str(path) for path in unique)
        )
    return unique[0]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def detect_delimiter(header_line: str) -> str:
    counts = {
        "\t": header_line.count("\t"),
        ",": header_line.count(","),
        ";": header_line.count(";"),
    }
    delimiter = max(counts, key=counts.get)
    if counts[delimiter] <= 0:
        raise PreparationError("Unable to detect CSV delimiter")
    return delimiter


def normalize_header(value: str) -> str:
    return value.strip().strip("<>").strip().lower().replace(" ", "_")


def parse_datetime(date_value: str, time_value: str, zone: ZoneInfo) -> datetime:
    raw_date = date_value.strip()
    raw_time = time_value.strip()
    date_formats = ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")
    time_formats = ("%H:%M:%S", "%H:%M", "%H%M%S", "%H%M")
    parsed_date = None
    parsed_time = None
    for pattern in date_formats:
        try:
            parsed_date = datetime.strptime(raw_date, pattern).date()
            break
        except ValueError:
            continue
    for pattern in time_formats:
        try:
            parsed_time = datetime.strptime(raw_time, pattern).time()
            break
        except ValueError:
            continue
    if parsed_date is None or parsed_time is None:
        raise PreparationError(
            f"Unsupported MT5 timestamp: {date_value!r} {time_value!r}"
        )
    return datetime.combine(parsed_date, parsed_time, tzinfo=zone)


def decimal_places(value: str) -> int:
    raw = value.strip()
    if not raw:
        return 0
    try:
        decimal_value = Decimal(raw)
    except InvalidOperation:
        return 0
    exponent = decimal_value.as_tuple().exponent
    return max(0, -exponent)


def analyze_csv(path: Path, source_timezone: str) -> CsvSummary:
    zone = ZoneInfo(source_timezone)
    size_bytes = path.stat().st_size
    sha256 = file_sha256(path)

    with path.open("r", encoding="utf-8-sig", newline="", errors="strict") as handle:
        header_line = handle.readline()
        if not header_line:
            raise PreparationError(f"Empty file: {path}")
        delimiter = detect_delimiter(header_line)
        handle.seek(0)
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise PreparationError(f"Missing header: {path}")
        mapped = {
            normalize_header(name): name
            for name in reader.fieldnames
            if name is not None
        }

        date_key = next(
            (mapped[key] for key in ("date", "datetime_date") if key in mapped),
            None,
        )
        time_key = next(
            (mapped[key] for key in ("time", "datetime_time") if key in mapped),
            None,
        )
        if date_key is None or time_key is None:
            raise PreparationError(
                f"MT5 DATE/TIME columns were not found in {path.name}: "
                f"{reader.fieldnames}"
            )

        price_keys = [
            mapped[key]
            for key in ("open", "high", "low", "close")
            if key in mapped
        ]
        if len(price_keys) != 4:
            raise PreparationError(
                f"OHLC columns were not found in {path.name}: {reader.fieldnames}"
            )

        volume_key = next(
            (
                mapped[key]
                for key in (
                    "tickvol",
                    "tick_volume",
                    "volume",
                    "vol",
                    "real_volume",
                )
                if key in mapped
            ),
            None,
        )
        if volume_key is None:
            raise PreparationError(
                f"No tick-volume/volume column found in {path.name}"
            )

        row_count = 0
        first_time = None
        last_time = None
        digits = 0
        nonzero_volume_rows = 0

        for row in reader:
            if not row or not any((value or "").strip() for value in row.values()):
                continue
            row_count += 1
            opened = parse_datetime(row[date_key], row[time_key], zone)
            if first_time is None:
                first_time = opened
            last_time = opened

            for key in price_keys:
                digits = max(digits, decimal_places(row[key]))

            raw_volume = (row.get(volume_key) or "").strip()
            try:
                if Decimal(raw_volume or "0") > 0:
                    nonzero_volume_rows += 1
            except InvalidOperation:
                pass

    if row_count < 1 or first_time is None or last_time is None:
        raise PreparationError(f"No data rows found in {path}")
    return CsvSummary(
        path=path,
        row_count=row_count,
        size_bytes=size_bytes,
        sha256=sha256,
        first_time=first_time,
        last_time=last_time,
        digits=digits,
        nonzero_volume_rows=nonzero_volume_rows,
        delimiter=delimiter,
    )


def aware_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def find_verified_profile(project_root: Path) -> dict | None:
    roots = (
        project_root / "examples",
        project_root / "data",
        project_root / "strategies",
    )
    required = {
        "digits",
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_tick_value_profit",
        "trade_tick_value_loss",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "calculation_mode",
        "currency_profit",
        "currency_margin",
    }
    current = (
        project_root
        / "strategies"
        / "ls_volume_delta"
        / "symbol_us30.yaml"
    ).resolve()

    for search_root in roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob("*.yaml"):
            if path.resolve() == current:
                continue
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("symbol", "")).upper() != SYMBOL:
                continue
            if not required.issubset(payload):
                continue
            status = str(
                (payload.get("metadata") or {}).get("verification_status", "")
            ).lower()
            if status.startswith("replace") or "placeholder" in status:
                continue
            payload = dict(payload)
            payload["schema_version"] = "1.0.0"
            payload["profile_id"] = PROFILE_ID
            payload["version"] = PROFILE_VERSION
            payload["symbol"] = SYMBOL
            metadata = dict(payload.get("metadata") or {})
            metadata["source_profile_path"] = (
                path.relative_to(project_root).as_posix()
            )
            metadata["verification_status"] = (
                "reused_project_verified_profile"
            )
            payload["metadata"] = stringify_metadata(metadata)
            return payload
    return None


def derived_profile(digits: int) -> dict:
    resolved_digits = max(0, min(8, digits))
    point = Decimal(1).scaleb(-resolved_digits)
    point_text = decimal_text(point)
    return {
        "schema_version": "1.0.0",
        "profile_id": PROFILE_ID,
        "version": PROFILE_VERSION,
        "symbol": SYMBOL,
        "digits": resolved_digits,
        "point": point_text,
        "trade_tick_size": point_text,
        "trade_tick_value": point_text,
        "trade_tick_value_profit": point_text,
        "trade_tick_value_loss": point_text,
        "trade_contract_size": "1",
        "volume_min": "0.01",
        "volume_max": "100",
        "volume_step": "0.01",
        "stops_level_points": 0,
        "freeze_level_points": 0,
        "calculation_mode": "cfd",
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "margin_initial": "0",
        "margin_maintenance": "0",
        "metadata": stringify_metadata(
            {
                "verification_status": "derived_from_us30_csv_for_research",
                "signal_parity": "price and R based",
                "cash_margin_parity": (
                    "replace with verified MT5 profile for broker-exact "
                    "cash and margin"
                ),
            }
        ),
    }


def stringify_metadata(
    values: dict[str, object],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, bool):
            result[str(key)] = "true" if value else "false"
        elif value is None:
            result[str(key)] = ""
        else:
            result[str(key)] = str(value)
    return result


def dump_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command))
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise PreparationError(
            f"Command failed with exit code {completed.returncode}: "
            + " ".join(command)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--source-timezone",
        default="Asia/Tehran",
        help="Timezone represented by the raw MT5 DATE/TIME fields",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Generate dataset/profile files but do not run vex-data import",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable package after a successful import report exists",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    data_root = project_root / "data" / "mt5"
    package_root = project_root / "strategies" / "ls_volume_delta"
    if not (project_root / "pyproject.toml").is_file():
        raise PreparationError(f"Not a VEX project root: {project_root}")
    if not package_root.is_dir():
        raise PreparationError(f"Strategy package not found: {package_root}")

    m1_path = resolve_data_file(data_root, M1_STEM)
    m15_path = resolve_data_file(data_root, M15_STEM)

    print(f"M1:  {m1_path}")
    print(f"M15: {m15_path}")
    m1 = analyze_csv(m1_path, args.source_timezone)
    m15 = analyze_csv(m15_path, args.source_timezone)

    if m1.nonzero_volume_rows == 0:
        raise PreparationError(
            "M1 volume is zero for every row; 2-minute Volume Delta cannot be built"
        )

    dataset = {
        "schema_version": "1.0.0",
        "dataset_id": DATASET_ID,
        "version": DATASET_VERSION,
        "name": "US30 M1 and M15 LS Volume Delta Dataset",
        "source": "mt5_csv",
        "root_path": "data/mt5",
        "price_basis": "bid",
        "source_timezone": args.source_timezone,
        "engine_timezone": "UTC",
        "files": [
            {
                "symbol": SYMBOL,
                "timeframe": "M1",
                "relative_path": m1.path.relative_to(data_root).as_posix(),
                "declared_start": aware_iso(m1.first_time),
                "declared_end": aware_iso(m1.last_time),
                "row_count": m1.row_count,
                "size_bytes": m1.size_bytes,
                "sha256": m1.sha256,
            },
            {
                "symbol": SYMBOL,
                "timeframe": "M15",
                "relative_path": m15.path.relative_to(data_root).as_posix(),
                "declared_start": aware_iso(m15.first_time),
                "declared_end": aware_iso(m15.last_time),
                "row_count": m15.row_count,
                "size_bytes": m15.size_bytes,
                "sha256": m15.sha256,
            },
        ],
        "metadata": stringify_metadata(
            {
                "strategy": "ls_volume_delta",
                "instrument": "US30_Dow_Jones",
                "source_clock": "stored_mt5_wall_clock",
                "source_timezone": args.source_timezone,
                "session_timezone": "Asia/Tehran",
                "m1_nonzero_volume_rows": m1.nonzero_volume_rows,
                "m1_delimiter": (
                    "tab" if m1.delimiter == "\t" else m1.delimiter
                ),
                "m15_delimiter": (
                    "tab" if m15.delimiter == "\t" else m15.delimiter
                ),
                "volume_delta": (
                    "clock-aligned causal M2 bars aggregated from M1"
                ),
                "trailing_m15_note": (
                    "the final M15 bar may be marked incomplete when M1 "
                    "does not include the final minute"
                ),
            }
        ),
    }
    dataset_path = package_root / "dataset.yaml"
    dump_yaml(dataset_path, dataset)

    profile = find_verified_profile(project_root)
    if profile is None:
        profile = derived_profile(max(m1.digits, m15.digits))
    profile_path = package_root / "symbol_us30.yaml"
    dump_yaml(profile_path, profile)

    package_path = package_root / "package.yaml"
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    package["symbol_profile_paths"] = ["symbol_us30.yaml"]
    package["import_report_path"] = (
        "../../data/cache/us30_mt5_ls/1/import-report.json"
    )
    package["enabled"] = False
    dump_yaml(package_path, package)

    summary = {
        "m1": {
            "file": m1.path.name,
            "rows": m1.row_count,
            "start": aware_iso(m1.first_time),
            "end": aware_iso(m1.last_time),
            "nonzero_volume_rows": m1.nonzero_volume_rows,
            "sha256": m1.sha256,
        },
        "m15": {
            "file": m15.path.name,
            "rows": m15.row_count,
            "start": aware_iso(m15.first_time),
            "end": aware_iso(m15.last_time),
            "sha256": m15.sha256,
        },
        "profile_status": profile["metadata"]["verification_status"],
    }
    (package_root / "prepared-data-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not args.skip_import:
        run(
            [
                "uv",
                "run",
                "vex-data",
                "import",
                "--project-root",
                ".",
                "--manifest",
                "strategies/ls_volume_delta/dataset.yaml",
                "--symbol-profile",
                "strategies/ls_volume_delta/symbol_us30.yaml",
                "--config",
                "strategies/ls_volume_delta/data_engine.yaml",
            ],
            project_root,
        )

    import_report = (
        project_root
        / "data"
        / "cache"
        / DATASET_ID
        / DATASET_VERSION
        / "import-report.json"
    )
    if args.enable:
        if not import_report.is_file():
            raise PreparationError(
                f"Import report does not exist: {import_report}"
            )
        package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
        package["enabled"] = True
        dump_yaml(package_path, package)
        print("Package enabled.")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"dataset: {dataset_path}")
    print(f"profile: {profile_path}")
    print(f"import report: {import_report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreparationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
