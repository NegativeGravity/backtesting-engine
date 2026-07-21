from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns

from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import OrderType, Side
from vex_contracts.market import Bar
from vex_contracts.orders import OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe

NS = 1_000_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the deterministic broker hot path")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--bars", type=int, default=100_000)
    parser.add_argument("--warmup", type=int, default=2_000)
    parser.add_argument(
        "--scenario",
        choices=("idle", "open-position", "historical-spread"),
        default="open-position",
    )
    parser.add_argument("--output")
    return parser.parse_args()


def percentile(values: list[int], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
    return ordered[index] / 1_000.0


def make_bar(sequence: int, start_time_ns: int, spread_points: int) -> Bar:
    open_time_ns = start_time_ns + (sequence - 1) * 60 * NS
    wave = sequence % 20
    close = 250_000 + (wave - 10)
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=open_time_ns,
        close_time_ns=open_time_ns + 60 * NS,
        open_ticks=250_000,
        high_ticks=250_020,
        low_ticks=249_980,
        close_ticks=close,
        tick_volume=100,
        real_volume=Decimal("0"),
        source_spread_points=spread_points,
        sequence=sequence,
    )


def configure_run(run: BacktestRunConfig, scenario: str) -> BacktestRunConfig:
    if scenario != "historical-spread":
        return run
    payload = run.model_dump(mode="python")
    payload["execution"]["spread"] = {
        "mode": "historical",
        "fallback_points": 7,
        "use_fallback_when_zero": True,
        "minimum_points": 1,
        "maximum_points": 80,
    }
    return BacktestRunConfig.model_validate(payload)


def submit_open_position(broker: BrokerSimulator, run: BacktestRunConfig, time_ns: int) -> None:
    broker.submit_order(
        OrderRequest(
            client_order_id="benchmark-position",
            run_id=run.run_id,
            strategy_instance_id=run.strategy.instance_id,
            symbol="XAUUSD",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume_lots=Decimal("0.10"),
            created_time_ns=time_ns,
            stop_loss_ticks=240_000,
            take_profit_ticks=260_000,
        )
    )


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    if args.bars <= 0 or args.warmup < 0:
        raise ValueError("bars must be positive and warmup must be non-negative")
    root = Path(args.project_root).resolve()
    run = BacktestRunConfig.model_validate(load_yaml(root / "examples/configs/run.yaml"))
    profile = SymbolProfile.model_validate(load_yaml(root / "examples/configs/symbol_xauusd.yaml"))
    run = configure_run(run, args.scenario)
    broker = BrokerSimulator(run, {profile.symbol: profile})
    start_time_ns = int(run.start_time.timestamp() * NS)
    spread_points = 0 if args.scenario == "historical-spread" else 7
    if args.scenario != "idle":
        submit_open_position(broker, run, start_time_ns)

    total = args.warmup + args.bars
    latencies: list[int] = []
    started = 0
    for sequence in range(1, total + 1):
        bar = make_bar(sequence, start_time_ns, spread_points)
        before = perf_counter_ns()
        broker.process_bar(bar)
        after = perf_counter_ns()
        if sequence == args.warmup:
            started = after
        elif sequence > args.warmup:
            latencies.append(after - before)
    finished = perf_counter_ns()
    if args.warmup == 0:
        started = finished - sum(latencies)
    elapsed_seconds = max((finished - started) / NS, sys.float_info.epsilon)
    report = broker.build_report(total)
    result: dict[str, object] = {
        "scenario": args.scenario,
        "bars": args.bars,
        "warmup_bars": args.warmup,
        "elapsed_seconds": elapsed_seconds,
        "bars_per_second": args.bars / elapsed_seconds,
        "latency_microseconds": {
            "mean": statistics.fmean(latencies) / 1_000.0 if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies, default=0) / 1_000.0,
        },
        "event_count": report.event_count,
        "order_count": report.order_count,
        "trade_count": report.trade_count,
        "open_position_count": report.open_position_count,
        "deterministic_digest": report.deterministic_digest,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
    }
    return result


def main() -> int:
    args = parse_args()
    result = run_benchmark(args)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
