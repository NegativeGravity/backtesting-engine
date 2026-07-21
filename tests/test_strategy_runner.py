from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from vex_contracts.data_engine import CacheArtifact, DataFileReport, DataImportReport
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.runner import StrategyBacktestRunner, datetime_to_ns

NS = 1_000_000_000
SHA = "0" * 64


def build_store(
    root: Path,
    run: BacktestRunConfig,
    bar_count: int = 50,
) -> ParquetBarStore:
    start_ns = datetime_to_ns(run.start_time)
    rows = []
    for sequence in range(bar_count):
        open_time_ns = start_ns + sequence * 60 * NS
        base = 260000 + sequence
        rows.append(
            {
                "symbol": "XAUUSD",
                "timeframe": "M1",
                "open_time_ns": open_time_ns,
                "close_time_ns": open_time_ns + 60 * NS,
                "open_ticks": base,
                "high_ticks": base + 10,
                "low_ticks": base - 10,
                "close_ticks": base + 1,
                "tick_volume": 100,
                "real_volume": 0,
                "source_spread_points": 0,
                "sequence": sequence,
                "is_complete": True,
                "source_row_number": sequence + 2,
            }
        )
    relative_path = "data/cache/strategy-test/XAUUSD/M1.parquet"
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(target)
    artifact = CacheArtifact(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        relative_path=relative_path,
        row_count=bar_count,
        complete_row_count=bar_count,
        incomplete_row_count=0,
        content_sha256=SHA,
        source_sha256=SHA,
        cache_key=SHA,
        size_bytes=target.stat().st_size,
    )
    report = DataImportReport(
        report_id="strategy_test_report",
        dataset_id=run.dataset.dataset_id,
        dataset_version=run.dataset.version,
        dataset_fingerprint=SHA,
        config_fingerprint=SHA,
        completion_watermark=datetime.fromtimestamp(
            rows[-1]["close_time_ns"] / NS,
            tz=UTC,
        ),
        success=True,
        source_row_count=bar_count,
        output_row_count=bar_count,
        complete_row_count=bar_count,
        incomplete_row_count=0,
        warning_count=0,
        error_count=0,
        files=(
            DataFileReport(
                symbol="XAUUSD",
                timeframe=Timeframe.M1,
                source_path="synthetic.csv",
                delimiter=",",
                source_row_count=bar_count,
                output_row_count=bar_count,
                complete_row_count=bar_count,
                incomplete_row_count=0,
                artifact=artifact,
            ),
        ),
    )
    return ParquetBarStore(root, report)


def load_models(
    project_root: Path,
) -> tuple[BacktestRunConfig, StrategyDescriptor, SymbolProfile]:
    run = BacktestRunConfig.model_validate(
        load_yaml(project_root / "examples/configs/run_strategy_smoke.yaml")
    )
    descriptor = StrategyDescriptor.model_validate(
        load_yaml(project_root / "examples/configs/strategy_sdk_smoke.yaml")
    )
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    m1_subscription = tuple(
        subscription for subscription in run.subscriptions if subscription.timeframe is Timeframe.M1
    )
    run = run.model_copy(update={"subscriptions": m1_subscription})
    descriptor = descriptor.model_copy(update={"subscriptions": m1_subscription})
    return run, descriptor, profile


def test_strategy_runner_is_deterministic(project_root: Path, tmp_path: Path) -> None:
    run, descriptor, profile = load_models(project_root)
    store = build_store(tmp_path, run)
    runtime = StrategyRuntimeConfig(
        warmup_bars_per_series=0,
        history_limit_per_series=100,
        callback_timeout_seconds=10,
    )
    first_recorder = StrategyOutputRecorder(retain_outputs=True)
    first = StrategyBacktestRunner(
        run,
        descriptor,
        runtime,
        {"XAUUSD": profile},
        store,
        first_recorder,
    ).run()
    second = StrategyBacktestRunner(
        run,
        descriptor,
        runtime,
        {"XAUUSD": profile},
        store,
        StrategyOutputRecorder(retain_outputs=True),
    ).run()

    assert first.broker_report.trade_count == 1
    assert first.action_count == 2
    assert first.chart_command_count > 20
    assert first.callbacks.start == 1
    assert first.callbacks.stop == 1
    assert first.deterministic_digest == second.deterministic_digest


def test_strategy_session_advances_exactly_one_close_batch_per_step(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from vex_strategy.session import StrategyBacktestSession

    run, descriptor, profile = load_models(project_root)
    store = build_store(tmp_path, run, bar_count=8)
    runtime = StrategyRuntimeConfig(
        warmup_bars_per_series=0,
        history_limit_per_series=100,
        callback_timeout_seconds=10,
    )
    session = StrategyBacktestSession(
        run,
        descriptor,
        runtime,
        {"XAUUSD": profile},
        store,
        StrategyOutputRecorder(retain_outputs=True),
    )
    try:
        started = session.start()
        assert started.processed_close_batches == 0
        assert started.processed_execution_bars == 0

        first = session.step()
        assert first.processed_close_batches == 1
        assert first.processed_execution_bars == 1
        assert len(first.execution_bars) == 1
        assert first.event_time_ns == first.execution_bars[0].close_time_ns

        second = session.step()
        assert second.processed_close_batches == 2
        assert second.processed_execution_bars == 2
        assert len(second.execution_bars) == 1
        assert second.event_time_ns > first.event_time_ns
    finally:
        if not session.finished:
            session.terminate()
