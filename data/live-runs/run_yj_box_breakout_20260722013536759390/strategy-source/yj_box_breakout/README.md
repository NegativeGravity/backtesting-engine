# YJ Box Breakout Strategy

This package implements the execution path from `yj-strategy.ipynb` inside the VEX engine.

Source notebook SHA-256:

```text
cd2439ebdfa813c9c52d0b528f21a81c03d6ee31c856e8f67215b4087039fc23
```

## Strategy rules

- Symbol and timeframe: XAUUSD M15.
- Time basis: timestamps are interpreted exactly as stored in the MT5 dataset. No timezone conversion is performed by the strategy.
- The daily box contains exactly eight bars with open times from 01:30 through 03:15. An incomplete box is skipped.
- From the 03:30 bar onward, the first valid breakout is traded:
  - open at or above box high: long at the bar open;
  - open at or below box low: short at the bar open;
  - open inside the box and both boundaries touched: cancel both entries as an ambiguous day;
  - only box high touched: long at box high;
  - only box low touched: short at box low.
- The pending entry pair is OCO and expires at the next stored-clock midnight.
- If another trade is still open when a new box becomes tradable, the new pair remains pending. When that position closes, the pair is re-evaluated on the same M15 bar and then on subsequent bars until midnight, matching the notebook's deferred daily-entry behavior.
- Initial risk is 1% of current account equity. Because entries are allowed only while flat, this equals current balance at sizing time.
- The target is 1.5R.
- Gap entries are sized again from their actual fill price, and their target is recalculated from the actual fill-to-stop distance.
- Stop loss has priority when stop and target are both touched in one M15 bar.
- A target-only touch may close the initial intrabar breakout on the same M15 candle, matching the notebook.
- When the initial leg is stopped, exactly one opposite reversal opens at the same stop fill price.
- The reversal is sized from the updated account after the initial loss, targets 1.5R, and cannot exit on the same M15 candle.
- No third leg is permitted.
- Any remaining position is closed at the final available close with `end_of_data`.

## Notebook-parity execution profile

The bundled run uses zero spread, zero commission, zero slippage, very high leverage, negative-balance permission, and fractional lot steps. These settings intentionally reproduce the notebook's mathematical model rather than a realistic broker account.

The VEX engine stores prices as integer ticks. XAUUSD therefore uses a 0.01 tick, and a 1.5R target that mathematically lands on a half-tick is rounded half-up to the nearest executable tick. This is the only deliberate price-precision difference from the notebook's floating-point implementation.

For OHLC-only intrabar fills, VEX records the engine event time. A fill that occurs somewhere inside a bar is shown at that bar's close event time because the exact tick timestamp is unavailable. Fill price, ordering, result, PnL, and bar association remain deterministic.

## Chart output

The strategy draws:

- the 01:30–03:30 box;
- extended box-high and box-low levels;
- initial and reversal entry markers;
- exit markers labelled `TP HIT`, `SL HIT`, `END OF DATA`, or `LIQUIDATED`;
- TradingView-style risk/reward boxes with leg, direction, open time, close time, net PnL, and R multiple.

The dashboard also renders its broker-derived trade overlay from authoritative fills and trades.
