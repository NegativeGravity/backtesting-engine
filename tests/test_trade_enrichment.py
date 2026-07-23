from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from vex_contracts.data_engine import CacheArtifact, DataFileReport, DataImportReport
from vex_contracts.enums import PositionSide
from vex_contracts.positions import Trade
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore
from vex_replay.trade_enrichment import export_trade_enriched_datasets

NS = 1_000_000_000
BAR_NS = 15 * 60 * NS
HASH = "0" * 64


def _ns(value: datetime) -> int:
    return int(value.timestamp() * NS)


def _models(project_root: Path) -> tuple[BacktestRunConfig, StrategyDescriptor, SymbolProfile]:
    strategy_root = project_root / "strategies/yj_box_breakout"
    run_data = load_yaml(strategy_root / "run.yaml")
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    run_data["run_id"] = "run_trade_enrichment_test"
    run_data["start_time"] = start.isoformat()
    run_data["end_time"] = end.isoformat()
    run = BacktestRunConfig.model_validate(run_data)
    descriptor = StrategyDescriptor.model_validate(load_yaml(strategy_root / "strategy.yaml"))
    profile = SymbolProfile.model_validate(
        load_yaml(strategy_root / "symbol_xauusd_fractional.yaml")
    )
    return run, descriptor, profile


def _source_table(start_ns: int) -> pa.Table:
    sequences = list(range(8))
    open_times = [start_ns + sequence * BAR_NS for sequence in sequences]
    close_times = [value + BAR_NS for value in open_times]
    highs = [1005, 1008, 1007, 1002, 1004, 1016, 1008, 1002]
    lows = [995, 998, 994, 989, 988, 997, 994, 992]
    return pa.table(
        {
            "symbol": pa.array(["XAUUSD"] * 8, type=pa.string()),
            "timeframe": pa.array(["M15"] * 8, type=pa.string()),
            "open_time_ns": pa.array(open_times, type=pa.int64()),
            "close_time_ns": pa.array(close_times, type=pa.int64()),
            "open_ticks": pa.array([1000] * 8, type=pa.int64()),
            "high_ticks": pa.array(highs, type=pa.int64()),
            "low_ticks": pa.array(lows, type=pa.int64()),
            "close_ticks": pa.array([1000] * 8, type=pa.int64()),
            "tick_volume": pa.array([100] * 8, type=pa.int64()),
            "real_volume": pa.array([0] * 8, type=pa.int64()),
            "source_spread_points": pa.array([0] * 8, type=pa.int64()),
            "sequence": pa.array(sequences, type=pa.int64()),
            "is_complete": pa.array([True] * 8, type=pa.bool_()),
        }
    )


def _report(source_relative_path: str, start: datetime, end: datetime) -> DataImportReport:
    artifact = CacheArtifact(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        relative_path=source_relative_path,
        row_count=8,
        complete_row_count=8,
        incomplete_row_count=0,
        content_sha256=HASH,
        source_sha256=HASH,
        cache_key=HASH,
        size_bytes=1,
    )
    file_report = DataFileReport(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        source_path="data/mt5/test.csv",
        delimiter=",",
        source_row_count=8,
        output_row_count=8,
        complete_row_count=8,
        incomplete_row_count=0,
        actual_start=start,
        actual_end=end,
        artifact=artifact,
    )
    return DataImportReport(
        report_id="report_trade_enrichment_test",
        dataset_id="xauusd_mt5_yj_tehran",
        dataset_version="1",
        dataset_fingerprint=HASH,
        config_fingerprint=HASH,
        completion_watermark=end,
        success=True,
        source_row_count=8,
        output_row_count=8,
        complete_row_count=8,
        incomplete_row_count=0,
        warning_count=0,
        error_count=0,
        files=(file_report,),
    )


def _trades(run_id: str, start_ns: int) -> tuple[Trade, Trade]:
    stopped_long = Trade(
        trade_id="trade_long_stopped",
        position_id="position_long_stopped",
        run_id=run_id,
        strategy_instance_id="yj_box_breakout_primary",
        symbol="XAUUSD",
        side=PositionSide.LONG,
        volume_lots=Decimal("1"),
        entry_time_ns=start_ns + 2 * BAR_NS,
        exit_time_ns=start_ns + 4 * BAR_NS,
        entry_price_ticks=Decimal("1000"),
        exit_price_ticks=Decimal("990"),
        entry_order_id="order_long_entry",
        entry_client_order_id="client_long_entry",
        entry_tags={"chain_id": "chain_2025-01-02", "trade_date": "2025-01-02", "leg": "1"},
        stop_loss_ticks=990,
        take_profit_ticks=1015,
        gross_pnl=Decimal("-100"),
        commission=Decimal("0"),
        spread_cost=Decimal("0"),
        slippage_cost=Decimal("0"),
        swap=Decimal("0"),
        net_pnl=Decimal("-100"),
        initial_risk=Decimal("100"),
        realized_r_multiple=Decimal("-1"),
        mae=Decimal("100"),
        mfe=Decimal("20"),
        exit_reason="stop_loss",
    )
    overlapping_short = Trade(
        trade_id="trade_short_target",
        position_id="position_short_target",
        run_id=run_id,
        strategy_instance_id="yj_box_breakout_primary",
        symbol="XAUUSD",
        side=PositionSide.SHORT,
        volume_lots=Decimal("2"),
        entry_time_ns=start_ns + 3 * BAR_NS,
        exit_time_ns=start_ns + 7 * BAR_NS,
        entry_price_ticks=Decimal("1005"),
        exit_price_ticks=Decimal("995"),
        entry_order_id="order_short_entry",
        entry_client_order_id="client_short_entry",
        entry_tags={"chain_id": "chain_2025-01-03", "trade_date": "2025-01-03", "leg": "1"},
        stop_loss_ticks=1015,
        take_profit_ticks=995,
        gross_pnl=Decimal("200"),
        commission=Decimal("0"),
        spread_cost=Decimal("0"),
        slippage_cost=Decimal("0"),
        swap=Decimal("0"),
        net_pnl=Decimal("200"),
        initial_risk=Decimal("200"),
        realized_r_multiple=Decimal("1"),
        mae=Decimal("50"),
        mfe=Decimal("200"),
        exit_reason="take_profit",
    )
    return stopped_long, overlapping_short


def test_full_dataset_is_preserved_and_overlapping_trades_are_not_overwritten(
    tmp_path: Path,
    project_root: Path,
) -> None:
    run, descriptor, profile = _models(project_root)
    start = run.start_time
    end = run.end_time
    source_path = tmp_path / "data/cache/test/source.parquet"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_table = _source_table(_ns(start))
    pq.write_table(source_table, source_path)
    report = _report(source_path.relative_to(tmp_path).as_posix(), start, end)
    store = ParquetBarStore(tmp_path, report)
    bundle_root = tmp_path / "data/replay/runs" / run.run_id

    result = export_trade_enriched_datasets(
        project_root=tmp_path,
        bundle_root=bundle_root,
        run=run,
        descriptor=descriptor,
        store=store,
        profiles=(profile,),
        trades=_trades(run.run_id, _ns(start)),
    )

    source_after = pq.read_table(source_path)
    assert result.execution_dataset is not None
    enriched = pq.read_table(result.execution_dataset)
    assert source_after.schema == source_table.schema
    assert source_after.num_rows == 8
    assert enriched.num_rows == source_after.num_rows
    assert "active_trade_ids" in enriched.column_names
    overlap_ids = set(enriched["active_trade_ids"][2].as_py())
    assert overlap_ids == {"trade_long_stopped", "trade_short_target"}

    candle_map = pq.read_table(result.candle_trade_map)
    overlap_rows = candle_map.filter(
        pc.equal(candle_map["sequence"], pa.scalar(2, type=pa.int64()))
    )
    assert set(overlap_rows["trade_id"].to_pylist()) == overlap_ids

    with result.trades_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = {row["trade_id"]: row for row in csv.DictReader(stream)}
    stopped = rows["trade_long_stopped"]
    assert stopped["stop_hunt_recovered_entry_4"] == "True"
    assert stopped["stop_hunt_reached_original_target_4"] == "True"
    assert stopped["bars_to_recover_entry_4"] == "1"
    assert stopped["bars_to_original_target_4"] == "2"

    summary = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert summary["market_dataset_rows"]["XAUUSD:M15"] == 8
    assert summary["stopped_then_recovered_entry_count"] == 1
    assert summary["stopped_then_reached_original_target_count"] == 1
    assert summary["unmapped_entry_trade_count"] == 0
    assert summary["unmapped_exit_trade_count"] == 0
