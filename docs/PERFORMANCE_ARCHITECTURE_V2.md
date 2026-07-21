# Vex Backtesting Engine — Performance Architecture V2

## Goals

The V2 architecture keeps deterministic candle ordering and no-look-ahead guarantees while removing avoidable UI, storage, pricing, and scheduling overhead. The engine remains exact at the configured candle fidelity; faster execution must not alter order activation, protection handling, broker event ordering, or deterministic digests.

## Implemented data path

```text
MT5 files
  -> independent file import workers
  -> strict row validation and fixed-point tick conversion
  -> Arrow record batches
  -> atomic Parquet artifacts
  -> cross-timeframe audit after all imports complete
```

`DataEngineConfig.file_import_workers` controls independent-file concurrency:

- `0`: automatic, capped conservatively to avoid disk thrashing
- `1`: fully serial, preferred for slow HDDs
- `2..N`: explicit parallel imports for SSD/NVMe and multi-file datasets

Parallelism is only applied between independent files. Row ordering and validation inside a single file remain deterministic.

## Implemented execution path

```text
monotonic deadline pacer
  -> strategy process cycle
  -> deterministic broker processing
  -> result coalescer
  -> adaptive 8–30 UI publications/second
  -> WebSocket worker
  -> incremental chart update
```

The engine rate and rendering rate are now independent. A fast run may process tens of thousands of bars per second while the browser receives a bounded visual stream. Publication frequency drops as replay speed rises. When an incremental frame exceeds 1,200 bars, the server emits a visual reset containing the latest 1,000 bars instead of serializing the entire interval. Pausing flushes the latest pending state immediately.

The old `processing time + sleep(1 / speed)` behavior has been replaced with monotonic deadline pacing. Processing time is subtracted from the next delay, reducing drift and making requested speed more accurate.

## Broker fidelity improvements

Spread configuration supports:

```yaml
spread:
  mode: historical
  fallback_points: 7
  use_fallback_when_zero: true
  minimum_points: 1
  maximum_points: 80
```

Historical spread is resolved for every bar from `source_spread_points`, bounded by the configured minimum and maximum, converted to executable ticks, and used consistently for:

- market and pending fills
- stop-loss and take-profit fills
- liquidation fills
- spread-cost accounting
- bid/ask position marking

Fixed spread remains backward compatible.

## Replay storage

New replay bundles contain periodic broker-state checkpoints:

```text
broker_state_snapshots
  - time_ns
  - event_sequence
  - active orders
  - positions
```

State reconstruction now loads the nearest checkpoint and applies only the event delta after that checkpoint. Replay bundles also contain an indexed `terminal_orders` table so cursor state no longer deserializes every historical order just to discover terminal states.

Read-only SQLite connections are reused per request thread with:

- query-only mode
- bounded page cache
- memory mapping
- file-generation detection
- immutable read-only access

Bootstrap history is bounded to the latest 5,000 fills/trades and latest 50,000 timeline rows at repository level; the live stream sends only the latest 5,000 timeline rows and entities. Full analytics continue to use the persisted dataset rather than the bounded browser payload.

## WebSocket backpressure and recovery

Live updates are coalesced at an adaptive 8–30 Hz. Each subscriber has a bounded queue. Queue overflow no longer silently discards a single causal event and continues with an inconsistent client state. Instead:

1. the queue is drained,
2. a `resync_required` control message is emitted,
3. the Web Worker reconnects,
4. the server sends a fresh authoritative bootstrap.

This preserves browser responsiveness without allowing silent state divergence.

## Frontend rendering

The browser pipeline is:

```text
WebSocket
  -> dedicated Web Worker
  -> frame merge/coalescing
  -> reducer broker snapshot reconciliation
  -> ring-buffer candles
  -> incremental lightweight-charts updates
  -> Canvas drawing overlay
```

The chart now:

- follows the newest candle by default,
- preserves the configured visible-bar count and right offset,
- shifts the logical range as new bars arrive,
- keeps price autoscale enabled unless the user explicitly locks Y,
- recovers from canvas/chart failures without stopping the engine,
- reconciles live orders and positions from each authoritative account snapshot.

## TradingView-style broker trade overlays

Trade boxes are generated from broker truth rather than strategy annotations. Closed trades and open positions display:

- long/short direction
- risk and reward areas
- entry line
- stop-loss line and price
- take-profit line and price
- exact open timestamp and entry price
- exact close/live timestamp and exit/current price
- Net PnL
- `TP HIT`, `SL HIT`, `LIQUIDATED`, `CLOSED`, or `OPEN`
- intrabar ambiguity warning

Strategy risk/reward drawings carrying the same `trade_id` are suppressed to prevent duplicate boxes.

## Correct concurrency placement

### Threads

Used for I/O-bound or coordination work:

- independent MT5 file ingestion
- live-run control loop
- WebSocket/API I/O
- SQLite read reuse per server thread
- browser Web Worker for message parsing and coalescing

### Processes

Used for fault and GIL isolation:

- each strategy runtime runs in a spawned child process
- multiple independent live runs naturally use independent strategy processes
- parameter sweeps and walk-forward folds should be scheduled as independent processes

### Intentionally sequential within one run

Broker/account state is causal. Bars inside a single run cannot be processed in arbitrary parallel order without changing results. The correct optimization targets are batching, allocation reduction, compiled kernels, and shared-memory transport—not concurrent mutation of one account ledger.

## Recommended final deployment topology

```text
React Dashboard
  -> REST / WebSocket Gateway
  -> Run Control Plane
  -> bounded Run Scheduler
  -> independent Run Workers
       -> Strategy Process
       -> Broker Kernel
       -> Arrow/Parquet Data Reader
       -> append-only Replay Writer
  -> immutable Replay Repository
  -> Analytics Service
```

For horizontal scale, completed replay bundles should be immutable and served from object storage or a shared filesystem. Run workers should write to isolated working directories and publish bundles atomically only after digest verification.

## Benchmarking

Run the broker benchmark with:

```bash
PYTHONPATH=src python benchmarks/benchmark_broker.py \
  --bars 100000 \
  --warmup 2000 \
  --scenario open-position \
  --output benchmark.json
```

Available scenarios:

- `idle`
- `open-position`
- `historical-spread`

The benchmark reports throughput, mean/p50/p95/p99/max latency, event counts, and deterministic digest. Performance results are machine-specific and must be compared on identical hardware and Python builds.

## Remaining high-cost architecture work

The following changes are deliberately not simulated by superficial wrappers because they require a versioned runtime protocol and differential validation:

1. shared-memory/Arrow IPC between engine and strategy process,
2. multi-cycle strategy batching while preserving broker feedback ordering,
3. serializable strategy checkpoints for constant-time live rewind,
4. native fixed-point broker kernel through Rust/PyO3,
5. tick/order-book execution fidelity and calibrated market impact.

These should be introduced behind new execution modes and verified against the existing deterministic digest and MT5 golden tests. They are the next step after measuring real profiles with the included benchmark suite.
