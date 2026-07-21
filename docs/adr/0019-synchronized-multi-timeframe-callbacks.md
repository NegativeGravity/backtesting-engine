# ADR 0019: Synchronized Multi-Timeframe Callbacks

## Status

Accepted.

## Decision

All closed bars sharing one close timestamp are installed in the strategy market view before any callback for that timestamp runs. Bar callbacks then execute in descriptor subscription order. Closed-only subscriptions never expose an unfinished higher-timeframe candle. Forming access must be declared explicitly and receives an OHLC snapshot aggregated only from execution bars observed by that time.

## Consequences

- An M1 callback can safely read an H1 bar that closed at the same timestamp.
- Callback order is deterministic and independent of file ordering.
- Strategy authors must guard the callback timeframe when a rule should run once per execution candle.
- Forming-bar values do not use the final source OHLC.
