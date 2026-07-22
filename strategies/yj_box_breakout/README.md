# YJ Box Breakout Strategy

This package implements the execution path from `yj-strategy.ipynb` inside the VEX engine.

Source notebook SHA-256:

```text
cd2439ebdfa813c9c52d0b528f21a81c03d6ee31c856e8f67215b4087039fc23
```

## Strategy rules

- Symbol and timeframe: XAUUSD M15.
- Session timezone: `Asia/Tehran`. The Data Engine converts the configured source timezone to UTC, and the strategy converts every bar back to Tehran before deriving the trading date, minute of day, box window, order expiry, and chart labels.
- The daily box is therefore always `01:30 <= Tehran time < 03:30`, independent of the machine timezone.
- The daily box contains exactly eight consecutive M15 bars with Tehran open times from 01:30 through 03:15. In notebook-parity mode, a partial box fails the run instead of being silently skipped.
- Both breakout directions are armed simultaneously as an OCO pair from the Tehran 03:30 bar onward. The first valid side is traded:
  - open at or above box high: long at the bar open;
  - open at or below box low: short at the bar open;
  - open inside the box and both boundaries touched: cancel both entries as an ambiguous day;
  - only box high touched: long at box high;
  - only box low touched: short at box low.
- The pending entry pair is OCO and expires at the next Tehran midnight. A fill on one side cancels the opposite side.
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

The parity symbol profile uses a 0.001 price tick and a 1e-12 lot step. Source prices with two decimals remain exact, while 1.5R targets that land on a half-cent remain representable without changing the notebook execution path.

For OHLC-only intrabar fills, VEX records the engine event time. A fill that occurs somewhere inside a bar is shown at that bar's close event time because the exact tick timestamp is unavailable. Fill price, ordering, result, PnL, and bar association remain deterministic.

## Chart output

The strategy draws:

- the 01:30–03:30 box;
- extended box-high and box-low levels;
- initial and reversal entry markers;
- exit markers labelled `TP HIT`, `SL HIT`, `END OF DATA`, or `LIQUIDATED`;
- TradingView-style risk/reward boxes with leg, direction, open time, close time, net PnL, and R multiple.

The dashboard also renders its broker-derived trade overlay from authoritative fills and trades.

## Exact data import

The YJ package has a dedicated M15 dataset cache because its notebook-parity symbol profile uses 0.001 price ticks and 1e-12 lot sizing. Build it with:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\import-yj-data.ps1
```

The bundled source manifest declares the CSV clock as UTC and the strategy converts engine timestamps to `Asia/Tehran`. If the raw MT5 CSV is exported in another broker timezone, change only `source_timezone` and the declared offsets in `dataset.yaml`; the strategy session must remain `Asia/Tehran`.
