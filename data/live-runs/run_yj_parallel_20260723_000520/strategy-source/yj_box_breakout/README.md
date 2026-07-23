# YJ Box Breakout Strategy

This package implements the YJ XAUUSD M15 box-breakout rules inside the VEX engine.

Reference notebook SHA-256:

```text
cd2439ebdfa813c9c52d0b528f21a81c03d6ee31c856e8f67215b4087039fc23
```

## Important execution modes

The reference notebook owns one global `position` variable and only opens a new daily trade while that variable is `None`. Therefore the notebook itself is single-position.

VEX 1.3.0 keeps the notebook's execution rules independently for every daily chain and adds an explicit parallel-chain mode:

```yaml
allow_overlapping_daily_chains: true
```

When this mode is enabled, a position from an earlier day may remain open while a later day's independent OCO breakout pair is armed and filled. Each chain keeps its own box, stop, target, reversal state, drawings, and broker identity. Set the option to `false`, restore the risk limits to one position, and disable pyramiding for the original single-position notebook behavior.

## Per-chain strategy rules

- Symbol and timeframe: XAUUSD M15.
- Stored MT5 wall clock is mapped to `Asia/Tehran`, converted to canonical UTC by the Data Engine, and converted back to Tehran by the strategy. Raw `01:30` therefore remains strategy `01:30`.
- The box contains exactly eight consecutive M15 bars with Tehran open times from 01:30 through 03:15.
- From the 03:30 bar onward both breakout directions are armed as a chain-local OCO pair:
  - open at or above box high: long at the bar open;
  - open at or below box low: short at the bar open;
  - open inside the box and both boundaries touched: cancel that day's pair as ambiguous;
  - only box high touched: long at box high;
  - only box low touched: short at box low.
- A fill on one side cancels only the sibling order belonging to the same daily chain.
- The untriggered pair expires at the next Tehran midnight.
- Initial risk is 1% of current realized account balance.
- Target is 1.5R from the actual fill price to that chain's own opposite box edge.
- Gap fills are resized from the actual fill price and recalculate their target.
- Stop loss has priority when stop and target are touched in the same M15 bar.
- A target-only touch may close an initial breakout on its entry candle.
- If leg 1 stops, exactly one opposite leg 2 opens at the stop fill price.
- The reversal is sized from updated realized balance, cannot exit on its creation candle, and cannot generate a third leg.
- Remaining positions are closed at the final available close with `end_of_data`.

## Parallel-chain isolation

Every entry position now carries immutable authoritative metadata copied from its originating order:

- `entry_order_id`
- `entry_client_order_id`
- `entry_tags.chain_id`
- `entry_tags.trade_date`
- `entry_tags.leg`

Protective orders remain bound to `position_id`. A stop in one chain therefore cannot close, redraw, or reverse another chain. Broker-generated reversals inherit the original chain and trade date and are tagged as leg 2.

## Execution profile

The bundled run uses zero spread, zero commission, zero slippage, very high leverage, negative-balance permission, hedging mode, fractional lot sizing, and higher concurrent-position limits. These settings reproduce the mathematical YJ rules and allow the requested overlapping daily chains; they are not a realistic broker-risk profile.

The parity symbol profile uses a 0.001 price tick and a 1e-12 lot step. Source prices with two decimals remain exact, and half-cent 1.5R targets remain representable.

## Chart output

The strategy draws:

- the forming and completed 01:30–03:30 box;
- persistent box-high and box-low levels;
- chain/date/leg-aware entry markers;
- exit markers labelled `TP HIT`, `SL HIT`, `END OF DATA`, or `LIQUIDATED`;
- TradingView-style risk/reward boxes.

The dashboard broker overlay is keyed by `position_id` or `trade_id` and displays the authoritative trade date and leg. Historical YJ boxes remain available for audit when revisiting the trade date.
