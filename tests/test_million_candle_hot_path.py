from decimal import Decimal
from pathlib import Path

from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import OrderType, Side
from vex_contracts.orders import OrderCancellationRequest, OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile


def _broker(project_root: Path) -> tuple[BrokerSimulator, BacktestRunConfig]:
    run = BacktestRunConfig.model_validate(load_yaml(project_root / "examples/configs/run.yaml"))
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    return BrokerSimulator(run, {"XAUUSD": profile}), run


def test_strategy_snapshot_is_bounded_after_large_terminal_history(project_root: Path) -> None:
    broker, run = _broker(project_root)
    for index in range(1_000):
        broker.submit_order(
            OrderRequest(
                client_order_id=f"bounded_{index}",
                run_id=run.run_id,
                strategy_instance_id=run.strategy.instance_id,
                symbol="XAUUSD",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                volume_lots=Decimal("0.01"),
                created_time_ns=index + 1,
                price_ticks=1,
            )
        )
        order_id = next(reversed(broker.state.orders))
        broker.cancel_order(
            OrderCancellationRequest(order_id=order_id, requested_time_ns=index + 1)
        )

    first = broker.state_snapshot
    second = broker.state_snapshot

    assert first is second
    assert len(first.orders) == 512
    assert broker.aggregate_statistics.cancelled_orders == 1_000
    assert len(broker.state.events) <= 4_096


def test_live_report_uses_aggregate_counters_without_embedding_history(project_root: Path) -> None:
    broker, _ = _broker(project_root)
    report = broker.build_live_report(processed_bars=1_000_000)

    assert report.processed_bars == 1_000_000
    assert report.order_count == 0
    assert report.trade_count == 0
