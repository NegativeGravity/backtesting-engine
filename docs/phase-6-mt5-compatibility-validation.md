# Phase 6 — MT5 Compatibility Validation

## Scope

Phase 6 adds a Windows-host MT5 snapshot collector and a deterministic differential validator.

The phase does not place live orders. It validates the assumptions used by the candle broker simulator before future live execution work begins.

## Delivered Components

### MT5 Host Collector

The collector connects to an installed MetaTrader 5 terminal and captures:

- `terminal_info`
- `account_info`
- `symbol_info`
- `symbol_info_tick`
- `order_calc_profit`
- `order_calc_margin`

The password is read from an environment variable and is never written into the snapshot.

### Symbol Profile Generation

A broker-specific `SymbolProfile` can be generated directly from the captured symbol snapshot.

```powershell
uv run vex-mt5 profile `
  --project-root . `
  --snapshot data\mt5-compatibility\live-snapshot.json `
  --symbol XAUUSD `
  --output examples\configs\symbol_xauusd_live.yaml
```

### Differential Validation

```powershell
uv run vex-mt5 validate `
  --project-root . `
  --config examples\configs\mt5_validation.yaml `
  --output data\cache\mt5-compatibility-report.json
```

The validator compares the selected run and symbol profile with the MT5 account and symbol snapshot.

### Offline Fixture

`examples/mt5/xauusd_offline_snapshot.json` validates the full framework without requiring a terminal.

It is not proof of compatibility with the user's broker.

### SMA Cross Demo

The demo strategy exercises:

- Multi-timeframe data access
- Indicator series
- Long and short market orders
- Stop-loss and take-profit orders
- Position updates
- Trade boxes
- Structured logs
- Replay
- Analytics

Configuration files:

```text
examples/configs/strategy_sma_cross.yaml
examples/configs/run_sma_cross.yaml
```

## Acceptance Boundary

Phase 6 framework acceptance is complete when the offline fixture passes.

Broker acceptance is complete only after the user collects a live snapshot from the target MT5 broker and the resulting report has zero failed checks.
