import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from vex_broker.pricing import PriceResolver
from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import OrderType, PriceBasis, Side
from vex_contracts.market import Bar
from vex_contracts.orders import OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import dump_json, load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vex-broker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--project-root", default=".")
    smoke.add_argument("--run-config", default="examples/configs/run.yaml")
    smoke.add_argument("--symbol-profile", default="examples/configs/symbol_xauusd.yaml")
    smoke.add_argument(
        "--import-report",
        default="data/cache/xauusd_mt5_2025_2026/2/import-report.json",
    )
    smoke.add_argument("--bars", type=int, default=500)
    smoke.add_argument("--close-after", type=int, default=120)
    smoke.add_argument("--output", default="data/cache/broker-smoke-report.json")
    return parser


def _bar(row: dict[str, Any]) -> Bar:
    return Bar(
        symbol=str(row["symbol"]),
        timeframe=Timeframe(str(row["timeframe"])),
        open_time_ns=int(row["open_time_ns"]),
        close_time_ns=int(row["close_time_ns"]),
        open_ticks=int(row["open_ticks"]),
        high_ticks=int(row["high_ticks"]),
        low_ticks=int(row["low_ticks"]),
        close_ticks=int(row["close_ticks"]),
        tick_volume=int(row["tick_volume"]),
        real_volume=Decimal(str(row["real_volume"])),
        source_spread_points=int(row["source_spread_points"]),
        sequence=int(row["sequence"]),
    )


def _smoke(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve()
    run = BacktestRunConfig.model_validate(load_yaml(root / args.run_config))
    profile = SymbolProfile.model_validate(load_yaml(root / args.symbol_profile))
    store = ParquetBarStore.from_report_path(root, root / args.import_report)
    symbol = next(item.symbol for item in run.subscriptions)
    frame = store.load(
        symbol,
        run.execution_timeframe,
        complete_only=True,
        limit=args.bars,
    )
    if frame.height < 3:
        raise ValueError("broker smoke test requires at least three complete bars")
    broker = BrokerSimulator(run, {symbol: profile})
    bars = tuple(_bar(row) for row in frame.iter_rows(named=True))
    broker.process_bar(bars[0])
    entry_reference = (
        PriceResolver(
            profile,
            PriceBasis.BID,
            run.execution.spread,
        )
        .resolve(bars[0])
        .ask.close_ticks
    )
    stop = entry_reference - 500
    target = entry_reference + 1000
    volume = broker.size_position(symbol, entry_reference, stop)
    broker.submit_order(
        OrderRequest(
            client_order_id="broker_smoke_entry",
            run_id=run.run_id,
            strategy_instance_id=run.strategy.instance_id,
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume_lots=volume,
            created_time_ns=bars[0].close_time_ns,
            stop_loss_ticks=stop,
            take_profit_ticks=target,
        )
    )
    close_submitted = False
    processed = 1
    for index, bar in enumerate(bars[1:], start=1):
        broker.process_bar(bar)
        processed += 1
        if broker.open_positions and index >= args.close_after and not close_submitted:
            position = broker.open_positions[0]
            broker.submit_order(
                OrderRequest(
                    client_order_id="broker_smoke_exit",
                    run_id=run.run_id,
                    strategy_instance_id=run.strategy.instance_id,
                    symbol=symbol,
                    side=Side.SELL,
                    order_type=OrderType.MARKET,
                    volume_lots=position.volume_lots,
                    created_time_ns=bar.close_time_ns,
                    reduce_only=True,
                    position_id=position.position_id,
                )
            )
            close_submitted = True
        if close_submitted and not broker.open_positions:
            break
        if broker.trades and not broker.open_positions:
            break
    report = broker.build_report(processed)
    output = root / args.output
    dump_json(report, output)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.command == "smoke":
        return _smoke(args)
    raise ValueError(f"unsupported command: {args.command}")
