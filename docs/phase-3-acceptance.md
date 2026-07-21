# Phase 3 Acceptance

## Required Gates

- Ruff lint passes.
- Ruff formatting check passes.
- Pyright strict mode reports zero errors.
- All Phase 0, Phase 1, Phase 2, and Phase 3 tests pass.
- JSON Schema export matches committed schemas.
- Runtime, descriptor, and run examples validate.
- The strategy smoke run completes against the real XAUUSD Parquet cache.
- Running the same smoke run twice produces the same strategy, output, and broker digests.

## Verified Behavior

- Parameter validation occurs before `on_start`.
- Strategy entrypoints must resolve to `Strategy` subclasses.
- Worker startup failures propagate with tracebacks.
- Worker startup timeouts terminate the child process.
- Closed market history rejects look-ahead data.
- Historical retention is bounded.
- Forming higher-timeframe access requires explicit subscription permission.
- Forming OHLC uses only observed execution bars.
- Strategy order APIs emit immutable intents.
- Broker feedback is returned through bounded rounds.
- Chart drawing revisions increase deterministically.
- Strategy output streams are canonical and hashed.
- A full strategy lifecycle can open and close a position through the Phase 2 broker.

## Real Data Smoke Result

The accepted smoke run processes 250 synchronized close batches from the XAUUSD dataset.

```text
Processed execution bars: 250
Actions: 2
Trades: 1
Chart commands: 256
Action errors: 0
Strategy digest: fc0958a78a82beed1cc74944e0358be5c03fcc5b7227efc3966f85598ec8c094
Output digest: edc2df4a5a89a91ac762eae4aafca2e85a0676fdd2b6561e46a78091a2099b86
Broker digest: 2075aa912acf487fc2b5cba8931d6c9913a9de5fae3fd44e195fc5b9f3e57150
```

The smoke PnL is not a strategy-performance claim. It validates SDK, process, chart, order, broker, and report integration.
