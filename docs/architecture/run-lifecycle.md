# Run Lifecycle

```mermaid
sequenceDiagram
    participant UI as Dashboard
    participant API as Backtest API
    participant Queue as Redis
    participant Worker as Backtest Worker
    participant Strategy as Strategy Process
    participant Store as Result Store

    UI->>API: Submit BacktestRunConfig
    API->>API: Validate and fingerprint
    API->>Queue: Enqueue run
    Worker->>Queue: Claim run
    Worker->>Strategy: Start isolated strategy
    Worker->>Store: Persist run.started
    loop Deterministic event loop
        Worker->>Strategy: Publish visible market event
        Strategy->>Worker: Orders and chart commands
        Worker->>Store: Persist ordered events
        Worker-->>API: Progress update
        API-->>UI: Batched replay update
    end
    Worker->>Store: Persist results and snapshots
    Worker-->>API: run.completed
    API-->>UI: Final analytics available
```

## Ordering Rule

A run-local event sequence defines exact replay order. Market event time defines chronology. Emission time is operational metadata and never decides simulation order.
