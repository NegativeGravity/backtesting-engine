# External Strategy Packages

## Package layout

Every independently replaceable strategy lives in one directory:

```text
strategies/my_strategy/
├── __init__.py
├── package.yaml
├── strategy.py
├── strategy.yaml
├── run.yaml
├── runtime.yaml
└── README.md
```

Copy `strategies/_template` to create a package. Change every placeholder identifier and set `enabled: true` only after the package is complete.

## Package manifest

`package.yaml` connects the strategy to its contracts and data:

```yaml
schema_version: 1.0.0
package_id: my_strategy
descriptor_path: strategy.yaml
run_config_path: run.yaml
runtime_config_path: runtime.yaml
symbol_profile_paths:
  - ../../examples/configs/symbol_xauusd.yaml
import_report_path: ../../data/cache/xauusd_mt5_2025_2026/2/import-report.json
enabled: true
```

All paths are resolved relative to the package directory and must remain inside the project root.

## Entrypoint

`strategy.yaml` declares the worker entrypoint:

```yaml
strategy_id: my_strategy
name: My Strategy
version: 1.0.0
entrypoint: my_strategy.strategy:MyStrategy
```

The class must inherit from `vex_strategy.base.Strategy`. The package directory name must be importable and must contain `__init__.py`.

## Strategy lifecycle

```python
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext


class MyStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> None:
        ...

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        ...

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        ...

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        ...
```

The strategy may read market and portfolio views and may emit actions. It cannot mutate broker state directly.

## Indicators and drawings

A strategy declares and updates its own chart output through `context.chart`. Chart commands are captured in the replay timeline and rendered by the dashboard independently of the strategy implementation.

Typical calls include:

```python
context.chart.declare_series(...)
context.chart.plot_scalar(...)
context.chart.marker(...)
context.chart.rectangle(...)
context.chart.risk_reward(...)
```

Stable series and drawing identifiers allow incremental updates across candles.

## Hot replacement workflow

1. Add or replace a package under `strategies/`.
2. Refresh the catalog:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\strategy-refresh.ps1
```

3. Start a new run:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId my_strategy `
  -MaxCloseBatches 5000
```

At run creation the engine copies the complete package to `data/live-runs/<run_id>/strategy-source`. The worker, deterministic rewind, and replay finalizer all import from that snapshot. Existing runs therefore remain reproducible even when the package is edited while they are running. New runs use the refreshed package files. Keep each package self-contained, importable, and give it a unique package directory and entrypoint module.

## Parameter overrides

A run can override descriptor defaults without changing source files:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId my_strategy `
  -ParametersJson '{"risk_percent":"0.5","lookback":50}'
```

Parameters are validated inside the isolated strategy worker before candle processing begins.

## Safety rules

- Keep strategy modules import-safe; do not start threads or processes at module import time.
- Do not use global mutable state.
- Do not access future data or files outside the SDK.
- Use `Decimal` for money, volume, and risk values.
- Emit orders through `context.orders`.
- Emit drawings through `context.chart`.
- Emit diagnostics through `context.log`.
- Keep callback execution within configured timeouts.


## Candle ownership

The engine owns time advancement. Strategy code must never read CSV or Parquet files directly. Every `on_bar` callback receives one already-closed subscribed bar from the current synchronized close batch. With M1 execution, `step_forward` advances one M1 candle and also delivers any subscribed higher-timeframe candles closing at the same timestamp. Orders, drawings, and logs emitted by the strategy are completed before the next batch is read.

## Finalized source snapshot

Completed live runs contain:

```text
data/replay/runs/<run_id>/strategy-source/
```

The replay manifest records the snapshot path and SHA-256 tree digest. This source snapshot is part of the run provenance and should be archived with the replay bundle.
