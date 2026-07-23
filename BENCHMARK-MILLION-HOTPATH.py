import json
import time
from decimal import Decimal
from pathlib import Path

from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import OrderType, Side
from vex_contracts.orders import OrderCancellationRequest, OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile

root = Path(__file__).resolve().parent
run = BacktestRunConfig.model_validate(load_yaml(root / "examples/configs/run.yaml"))
profile = SymbolProfile.model_validate(load_yaml(root / "examples/configs/symbol_xauusd.yaml"))
broker = BrokerSimulator(run, {"XAUUSD": profile})

terminal_orders = 20_000
started = time.perf_counter()
for index in range(terminal_orders):
    timestamp = index + 1
    broker.submit_order(
        OrderRequest(
            client_order_id=f"benchmark_{index}",
            run_id=run.run_id,
            strategy_instance_id=run.strategy.instance_id,
            symbol="XAUUSD",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            volume_lots=Decimal("0.01"),
            created_time_ns=timestamp,
            price_ticks=1,
        )
    )
    order_id = next(reversed(broker.state.orders))
    broker.cancel_order(OrderCancellationRequest(order_id=order_id, requested_time_ns=timestamp))
history_seconds = time.perf_counter() - started

snapshot = broker.state_snapshot
loops = 2_000
started = time.perf_counter()
for _ in range(loops):
    snapshot = broker.state_snapshot
snapshot_seconds = time.perf_counter() - started

started = time.perf_counter()
for _ in range(loops):
    broker.build_live_report(1_000_000)
report_seconds = time.perf_counter() - started

result = {
    "terminal_orders": terminal_orders,
    "strategy_snapshot_orders": len(snapshot.orders),
    "history_setup_seconds": history_seconds,
    "cached_snapshot_average_microseconds": snapshot_seconds / loops * 1_000_000,
    "live_report_average_microseconds": report_seconds / loops * 1_000_000,
    "event_tail": len(broker.state.events),
}
print(json.dumps(result, indent=2))
