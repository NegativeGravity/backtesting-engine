# Phase 3 — Strategy SDK

## Objective

Phase 3 provides the execution boundary between independently developed strategies and the deterministic data and broker engines. It enables strategies to consume synchronized multi-timeframe bars, inspect broker snapshots, emit orders, define chart output, and run in a dedicated process without importing broker or dashboard implementations.

## Delivered Components

```text
src/vex_strategy/
├── actions.py
├── base.py
├── chart.py
├── cli.py
├── context.py
├── exceptions.py
├── executor.py
├── forming.py
├── isolation.py
├── loader.py
├── logging.py
├── market.py
├── orders.py
├── output.py
├── portfolio.py
├── protocol.py
├── runner.py
└── worker.py
```

The included `vex_example_strategies.sdk_smoke` strategy is an integration fixture, not a trading recommendation.

## Lifecycle

A strategy object persists for the entire run inside its own process.

```text
Load class
→ Validate parameters
→ Apply historical warmup
→ on_start
→ repeated synchronized cycles
   ├── update market view
   ├── update portfolio snapshot
   ├── on_order_update
   └── on_bar
→ on_stop
→ process exit
```

All bars in one synchronized close batch are applied before the first callback for that timestamp. Callback order follows the descriptor subscription order.

## Market View

The market view exposes only subscribed series. Closed history is bounded by `history_limit_per_series`. Warmup history is loaded from bars whose close time does not exceed the run start.

Available operations:

- latest closed bar with offset
- bounded historical window
- number of retained bars
- bars closed at the current clock time
- explicitly enabled forming higher-timeframe bar

The view rejects:

- unsubscribed symbols or timeframes
- clocks moving backward
- bars closing after the strategy clock
- conflicting bars with the same close time
- forming data without explicit permission

## Forming Higher-Timeframe Bars

The runner loads only source timeframe boundaries from the authoritative cache. Partial OHLC values are aggregated from execution bars already observed by the runtime.

```text
open        = first observed execution bar open
high        = highest observed execution bar high
low         = lowest observed execution bar low
close       = latest observed execution bar close
tick volume = sum of observed execution bar volumes
```

The final source OHLC is never used to construct a forming snapshot. When the interval closes, the forming snapshot is removed and the authoritative closed source bar is delivered normally.

## Order API

The strategy process emits immutable actions:

- submit market order
- submit limit order
- submit stop order
- cancel order
- modify pending order
- change position protection
- close or partially close a position

The parent action executor converts intents into the existing Phase 2 contracts. Strategy code cannot directly alter broker state.

Client order IDs and action IDs are deterministic per strategy process. Broker-generated IDs remain deterministic under the Phase 2 ID generator.

## Immediate Broker Feedback

Actions can generate order-created, accepted, rejected, modified, or cancelled events. The runner returns those events to the strategy through bounded feedback rounds at the same strategy clock time.

The limit prevents an accidental recursive action loop from running forever. Exceeding the configured limit fails the run rather than silently dropping behavior.

## Chart API

The SDK exposes vendor-neutral helpers for:

- panes
- line, area, histogram, and candle series
- scalar and candle points
- trend lines
- horizontal levels
- rectangles
- markers
- labels
- risk/reward trade boxes
- drawing deletion
- layer clearing

Each drawing is identified by `layer_id + drawing_id`. The first upsert uses revision zero and every update increments the revision. The dashboard adapter will later map these commands to TradingView Advanced Charts or Lightweight Charts.

## Strategy Isolation

The runtime uses `multiprocessing` with the `spawn` start method. This matches Windows behavior and prevents assumptions that only work under Unix `fork`.

Isolation guarantees in this phase:

- separate strategy memory
- persistent strategy object state
- startup timeout
- callback timeout
- shutdown timeout
- exception propagation
- crash detection
- forced process termination
- bounded callback output

Isolation does not yet guarantee:

- network denial
- filesystem sandboxing
- operating-system CPU quotas
- operating-system memory quotas
- untrusted-code security

Those controls belong in the later worker-container deployment layer.

## Output Recording

Three JSON Lines streams are produced:

```text
strategy-actions.jsonl
chart-commands.jsonl
strategy-logs.jsonl
```

Records use canonical sorted JSON. An incremental output digest is calculated without loading the entire timeline into memory.

## Deterministic Report

The strategy report contains:

- processed close batches
- processed execution bars
- callback counts
- action count
- chart command count
- log count
- feedback rounds
- action errors
- complete broker report
- output digest
- combined deterministic digest

The combined digest includes the run, descriptor, runtime configuration, callback statistics, output digest, and broker digest.

## Windows Execution

```powershell
uv sync --all-groups --python 3.12
powershell -ExecutionPolicy ByPass -File .\scripts\strategy-smoke.ps1
```

The strategy entrypoint must be importable from the environment created by `uv`.

## Extension Rules

A strategy must not:

- import `BrokerSimulator`
- import `ParquetBarStore`
- write directly to replay storage
- call chart-vendor APIs
- mutate contract models
- rely on local wall-clock time
- rely on nondeterministic random state

New SDK capabilities should be added through explicit context APIs and immutable actions.
