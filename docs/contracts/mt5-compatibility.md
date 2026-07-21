# MT5 Compatibility Contracts

## Snapshot

`Mt5CompatibilitySnapshot` is an immutable capture of the MT5 terminal, account, symbol rules, and broker-side calculation samples.

It contains:

- Terminal build and connectivity state
- Account currency, leverage, position mode, and stop-out thresholds
- Symbol precision, contract size, tick values, volume grid, margin fields, execution modes, and swap fields
- `order_calc_profit` and `order_calc_margin` samples for both buy and sell directions

The snapshot is collected on the Windows host because the official MetaTrader 5 Python integration communicates with an installed terminal.

## Generated Symbol Profile

`profile_from_snapshot` maps supported MT5 calculation modes to the engine `SymbolProfile` contract.

The generated profile stores additional MT5 fields in versioned metadata so unsupported execution details are never silently discarded.

## Validation Report

`Mt5CompatibilityReport` includes explicit checks for:

- Terminal connectivity and API availability
- Account currency, leverage, position mode, margin call, and stop-out levels
- Symbol calculation mode, precision, contract size, tick values, volume limits, stop levels, and margin fields
- Profit agreement with `order_calc_profit`
- Margin agreement with `order_calc_margin`

Every check is `passed`, `warning`, `failed`, or `skipped`.

The report is deterministic for identical snapshot, profile, run configuration, and tolerance inputs.
