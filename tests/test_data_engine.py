from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from vex_contracts.data_engine import DataEngineConfig
from vex_contracts.dataset import DatasetFile, DatasetManifest
from vex_contracts.enums import CacheMode, CalculationMode
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore
from vex_data_engine.engine import Mt5DataEngine
from vex_data_engine.exceptions import DataValidationError


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


def _write_dataset(root: Path, invalid_ohlc: bool = False) -> DatasetManifest:
    data = root / "data" / "mt5"
    data.mkdir(parents=True)
    m1_rows = [
        ("00:00:00", "100.00", "101.00", "99.00", "100.50", 10),
        ("00:01:00", "100.50", "102.00", "100.00", "101.00", 11),
        ("00:02:00", "101.00", "103.00", "100.50", "102.00", 12),
        ("00:03:00", "102.00", "104.00", "101.00", "103.00", 13),
        ("00:04:00", "103.00", "105.00", "102.00", "104.00", 14),
        ("00:05:00", "104.00", "106.00", "103.00", "105.00", 15),
    ]
    if invalid_ohlc:
        m1_rows[2] = ("00:02:00", "101.00", "100.00", "100.50", "102.00", 12)
    m1 = data / "XAUUSD_M1_202501010000_202501010005.csv"
    m1.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        + "".join(
            f"2025.01.01\t{time}\t{open_}\t{high}\t{low}\t{close}\t{volume}\t0\t2\n"
            for time, open_, high, low, close, volume in m1_rows
        ),
        encoding="utf-8",
    )
    m5 = data / "XAUUSD_M5_202501010000_202501010005.csv"
    m5.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.01\t00:00:00\t100.00\t105.00\t99.00\t104.00\t60\t0\t2\n"
        "2025.01.01\t00:05:00\t104.00\t106.00\t103.00\t105.00\t15\t0\t2\n",
        encoding="utf-8",
    )
    return DatasetManifest(
        dataset_id="test_dataset",
        version="1",
        name="Test Dataset",
        root_path="data/mt5",
        source_timezone="UTC",
        files=(
            DatasetFile(
                symbol="XAUUSD",
                timeframe=Timeframe.M1,
                relative_path=m1.name,
                declared_start=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
                declared_end=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
            ),
            DatasetFile(
                symbol="XAUUSD",
                timeframe=Timeframe.M5,
                relative_path=m5.name,
                declared_start=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
                declared_end=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
            ),
        ),
    )


def test_engine_imports_caches_audits_and_synchronizes(tmp_path: Path) -> None:
    manifest = _write_dataset(tmp_path)
    config = DataEngineConfig(
        cache_mode=CacheMode.REFRESH,
        cross_timeframe_audit=True,
        audit_base_timeframe=Timeframe.M1,
    )
    outcome = Mt5DataEngine(tmp_path).import_dataset(
        manifest,
        {"XAUUSD": _profile()},
        config,
    )

    assert outcome.report.success
    assert outcome.report.incomplete_row_count == 2
    assert outcome.report.cross_timeframe_reports[0].matching_bar_count == 1
    assert outcome.report.cross_timeframe_reports[0].mismatching_bar_count == 0

    store = ParquetBarStore(tmp_path, outcome.report)
    latest = store.latest_closed(
        "XAUUSD",
        Timeframe.M5,
        int(datetime(2025, 1, 1, 0, 5, tzinfo=UTC).timestamp() * 1_000_000_000),
    )
    assert latest is not None
    assert latest["close_ticks"] == 10400

    batches = tuple(store.iter_close_batches((("XAUUSD", Timeframe.M1), ("XAUUSD", Timeframe.M5))))
    assert batches[-1].close_time_ns == int(
        datetime(2025, 1, 1, 0, 5, tzinfo=UTC).timestamp() * 1_000_000_000
    )
    assert {bar["timeframe"] for bar in batches[-1].bars} == {"M1", "M5"}


def test_reuse_mode_reuses_valid_artifacts(tmp_path: Path) -> None:
    manifest = _write_dataset(tmp_path)
    engine = Mt5DataEngine(tmp_path)
    engine.import_dataset(
        manifest,
        {"XAUUSD": _profile()},
        DataEngineConfig(cache_mode=CacheMode.REFRESH),
    )
    outcome = engine.import_dataset(
        manifest,
        {"XAUUSD": _profile()},
        DataEngineConfig(cache_mode=CacheMode.REUSE),
    )

    assert all(file.artifact is not None and file.artifact.reused for file in outcome.report.files)


def test_invalid_ohlc_fails_and_writes_report(tmp_path: Path) -> None:
    manifest = _write_dataset(tmp_path, invalid_ohlc=True)

    with pytest.raises(DataValidationError):
        Mt5DataEngine(tmp_path).import_dataset(
            manifest,
            {"XAUUSD": _profile()},
            DataEngineConfig(cache_mode=CacheMode.REFRESH),
        )

    assert (tmp_path / "data" / "cache" / "test_dataset" / "1" / "import-report.json").exists()


def test_read_only_mode_requires_an_untampered_cache(tmp_path: Path) -> None:
    from vex_data_engine.exceptions import CacheMissError

    manifest = _write_dataset(tmp_path)
    engine = Mt5DataEngine(tmp_path)
    outcome = engine.import_dataset(
        manifest,
        {"XAUUSD": _profile()},
        DataEngineConfig(cache_mode=CacheMode.REFRESH, cross_timeframe_audit=False),
    )
    artifact = outcome.report.files[0].artifact
    assert artifact is not None
    cache_path = tmp_path / artifact.relative_path
    with cache_path.open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(CacheMissError):
        engine.import_dataset(
            manifest,
            {"XAUUSD": _profile()},
            DataEngineConfig(cache_mode=CacheMode.READ_ONLY, cross_timeframe_audit=False),
        )
