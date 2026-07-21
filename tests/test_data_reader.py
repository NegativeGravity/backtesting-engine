from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from vex_contracts.data_engine import DataEngineConfig
from vex_contracts.enums import CalculationMode
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.reader import read_mt5_csv


def _profile() -> SymbolProfile:
    return SymbolProfile(
        profile_id="xauusd_test",
        version="1.0.0",
        symbol="XAUUSD",
        calculation_mode=CalculationMode.CFD,
        currency_base="XAU",
        currency_profit="USD",
        currency_margin="USD",
        digits=2,
        point=Decimal("0.01"),
        trade_tick_size=Decimal("0.01"),
        trade_tick_value=Decimal("1"),
        trade_contract_size=Decimal("100"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
    )


def test_reader_parses_daily_without_time_and_marks_trailing_bar(tmp_path: Path) -> None:
    source = tmp_path / "XAUUSD_D1_202501010000_202501020000.csv"
    source.write_text(
        "<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.01\t100.00\t102.00\t99.00\t101.00\t10\t0\t2\n"
        "2025.01.02\t101.00\t103.00\t100.00\t102.00\t11\t0\t2\n",
        encoding="utf-8",
    )

    parsed = read_mt5_csv(
        source,
        "XAUUSD",
        Timeframe.D1,
        "UTC",
        _profile(),
        datetime(2025, 1, 2, tzinfo=UTC),
        DataEngineConfig(cross_timeframe_audit=False),
    )

    assert parsed.frame.height == 2
    assert parsed.frame["open_ticks"].to_list() == [10000, 10100]
    assert parsed.frame["is_complete"].to_list() == [True, False]
    assert parsed.frame["close_time_ns"][0] - parsed.frame["open_time_ns"][0] == 86_400_000_000_000


def test_reader_converts_broker_timezone_to_utc(tmp_path: Path) -> None:
    source = tmp_path / "XAUUSD_M1_202501010000_202501010000.csv"
    source.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.01\t00:00:00\t100.00\t101.00\t99.00\t100.50\t10\t0\t2\n",
        encoding="utf-8",
    )

    parsed = read_mt5_csv(
        source,
        "XAUUSD",
        Timeframe.M1,
        "Europe/Athens",
        _profile(),
        datetime(2025, 1, 1, tzinfo=UTC),
        DataEngineConfig(cross_timeframe_audit=False),
    )

    expected = int(datetime(2024, 12, 31, 22, 0, tzinfo=UTC).timestamp() * 1_000_000_000)
    assert parsed.frame["open_time_ns"][0] == expected


def test_reader_drops_trailing_incomplete_bar(tmp_path: Path) -> None:
    from vex_contracts.enums import TrailingBarPolicy

    source = tmp_path / "XAUUSD_M1_202501010000_202501010001.csv"
    source.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.01\t00:00:00\t100.00\t101.00\t99.00\t100.50\t10\t0\t2\n"
        "2025.01.01\t00:01:00\t100.50\t102.00\t100.00\t101.00\t11\t0\t2\n",
        encoding="utf-8",
    )

    parsed = read_mt5_csv(
        source,
        "XAUUSD",
        Timeframe.M1,
        "UTC",
        _profile(),
        datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        DataEngineConfig(
            cross_timeframe_audit=False,
            trailing_bar_policy=TrailingBarPolicy.DROP,
        ),
    )

    assert parsed.source_row_count == 2
    assert parsed.frame.height == 1
    assert parsed.frame["is_complete"].to_list() == [True]


def test_reader_reports_price_not_aligned_to_tick_size(tmp_path: Path) -> None:
    profile = _profile().model_copy(update={"trade_tick_size": Decimal("0.05")})
    source = tmp_path / "XAUUSD_M1_202501010000_202501010000.csv"
    source.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.01\t00:00:00\t100.03\t101.00\t99.00\t100.50\t10\t0\t2\n",
        encoding="utf-8",
    )

    parsed = read_mt5_csv(
        source,
        "XAUUSD",
        Timeframe.M1,
        "UTC",
        profile,
        datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        DataEngineConfig(cross_timeframe_audit=False),
    )

    assert parsed.frame.is_empty()
    assert any(issue.code == "PRICE_NOT_TICK_ALIGNED" for issue in parsed.issues)
