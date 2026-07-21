# ADR 0024 — Vendor-Neutral Chart Adapter

## Status

Accepted

## Context

The product should offer a TradingView-like experience without coupling strategy code or replay contracts to a specific licensed chart package.

## Decision

The frontend depends on a `ChartAdapter` interface. Lightweight Charts is the default implementation. A separate Advanced Charts adapter boundary is retained for deployments that have the required package and license.

## Consequences

- Strategies emit the same chart commands for every chart implementation.
- Licensed assets are not committed or redistributed.
- Chart vendor migration does not change the backtest engine or Strategy SDK.
