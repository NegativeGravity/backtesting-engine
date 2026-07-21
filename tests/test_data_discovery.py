from pathlib import Path

import pytest

from vex_contracts.timeframes import Timeframe
from vex_data_engine.discovery import discover_mt5_files, parse_mt5_filename
from vex_data_engine.exceptions import DataDiscoveryError


def test_filename_parser_normalizes_daily_and_windows_suffix() -> None:
    parsed = parse_mt5_filename("XAUUSD_Daily_202501020000_202607130000(2).csv")

    assert parsed.symbol == "XAUUSD"
    assert parsed.timeframe is Timeframe.D1
    assert parsed.canonical_name == "XAUUSD_D1_202501020000_202607130000.csv"


def test_discovery_rejects_duplicate_symbol_timeframe(tmp_path: Path) -> None:
    (tmp_path / "XAUUSD_M1_202501010000_202501010100.csv").write_text("x", encoding="utf-8")
    (tmp_path / "XAUUSD_M1_202501010000_202501010100(1).csv").write_text("x", encoding="utf-8")

    with pytest.raises(DataDiscoveryError):
        discover_mt5_files(tmp_path)
