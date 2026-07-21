# Phase 2: Broker Simulator

## Objective

Provide a deterministic MT5-oriented candle broker that converts strategy order requests into orders, fills, positions, trades, account snapshots, and replay events while applying configurable account and execution rules.

## Runtime Boundaries

The simulator consumes:

- `BacktestRunConfig`
- versioned `SymbolProfile` objects
- complete bars from the Phase 1 data engine
- validated `OrderRequest` objects

The simulator produces:

- deterministic order lifecycle events
- actual fills with execution-cost attribution
- hedging or netting positions
- completed trade records
- account snapshots
- broker state snapshots
- deterministic simulation reports

## Execution Lifecycle

1. The strategy submits an immutable order request.
2. The broker creates and validates an order.
3. Accepted orders activate on the next executable bar.
4. Market orders execute at the executable bar open.
5. Limit and stop orders evaluate gap conditions before intrabar ranges.
6. Filled entry orders update the portfolio and install protection orders.
7. Stop loss and take profit conditions are evaluated according to the intrabar policy.
8. Positions are marked to executable close-side prices.
9. Margin, equity, drawdown, margin call, and stop out are recalculated.
10. An account snapshot closes the broker step.

## Fill Rules

### Market

- Buy: ask open plus adverse market slippage.
- Sell: bid open minus adverse market slippage.

### Limit

- A marketable gap receives the better executable open price.
- Intrabar execution uses the limit price.
- Configured adverse slippage is capped so the fill is never worse than the limit.

### Stop

- A gap beyond the stop executes at the executable open price.
- Intrabar execution uses the stop level.
- Stop slippage is always adverse.

## Intrabar Ambiguity

When one candle touches both stop loss and take profit, the configured policy is applied:

- `conservative`
- `optimistic`
- `nearest_to_open`
- `stop_first`
- `target_first`
- `reject_ambiguous`

An entry and protection touched within the same candle is also treated as ambiguous. Conservative mode does not assume a profitable target occurred after an intrabar entry unless ordering is knowable.

## Account Model

The account tracks:

- balance
- equity
- floating PnL
- used margin
- free margin
- margin level
- peak equity
- drawdown amount
- drawdown percentage
- margin-call state

The following inputs remain configurable:

- initial balance
- account currency
- leverage
- position mode
- margin-call level
- stop-out level
- negative-balance policy
- maximum margin usage

## Position Sizing

The standalone sizing service supports:

- fixed lot
- risk percentage of current equity
- fixed cash risk
- strategy-defined volume

Calculated volume is floored to broker `volume_step` and constrained by `volume_min` and `volume_max`.

## Unsupported in Phase 2

- historical bid and ask candles
- tick-level path reconstruction
- partial order fills
- order-book queue simulation
- variable spread
- multi-currency account conversion
- swap scheduling
- futures without explicit initial margin
- exchange-specific IOC and FOK behavior

These boundaries are explicit so the simulator does not claim fidelity that candle data cannot provide.
