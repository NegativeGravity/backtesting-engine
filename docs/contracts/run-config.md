# Run Config Contract

The run config is the complete immutable input to one backtest request.

## Required Decisions

- Strategy and version
- Dataset and version
- Symbol profiles and versions
- Date range
- Execution timeframe
- Subscriptions
- Account model
- Execution cost model
- Risk limits
- Replay recording
- Random seed

## Validation

- Start must precede end.
- Subscriptions must be unique.
- Execution timeframe must be subscribed.
- Symbol profile references must be unique.
- Commission currency must equal account currency in schema version 1.
