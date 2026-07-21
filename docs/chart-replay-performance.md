# Chart Replay Performance and Scale Controls

Release 1.1.0 changes the replay chart update path from full-state redraws to bounded incremental updates.

## Supported chart timeframes

The dashboard exposes the six MT5 timeframes supplied by the project dataset:

- M1
- M5
- M15
- H1
- H4
- D1

Unavailable timeframes remain visible but disabled for a run that does not provide them.

## Viewport controls

The chart toolbar provides:

- Candle count presets for the horizontal scale
- Follow-latest mode
- Horizontal scale lock
- Price scale auto/lock mode
- Price-range recapture after manual adjustment
- Viewport reset
- Chart focus mode

Viewport settings are stored per symbol and timeframe in browser local storage. A locked price range is not auto-scaled when new replay candles arrive. A locked horizontal scale keeps the configured number of candles visible while following the newest candle.

## Smooth replay path

The browser coalesces consecutive advance frames to at most one React update per animation frame. Candle updates use the Lightweight Charts incremental series API. Strategy line series append only new points instead of replacing complete series data on each callback.

The React replay state keeps a bounded candle window and compacts the chart series periodically. This prevents the previous fixed-length window bug where the chart stopped receiving new candles after reaching the maximum retained bar count.

## Scale workflow

1. Select the required candle count.
2. Keep Follow and X Scale enabled for TradingView-style replay movement.
3. Drag the right price axis to the desired range.
4. Press Y Scale to lock the current range.
5. Press the save icon after another manual price-axis adjustment to replace the stored range.
6. Use the maximize icon for chart focus mode.

The settings remain active for the complete replay and are restored when the same symbol and timeframe are opened again.

## Exact horizontal scale capture

To preserve a manually selected horizontal scale, disable `X Scale`, zoom the chart with the mouse wheel or axis drag, and enable `X Scale` again. The current visible candle width and right offset are captured. While the lock is active, the adjacent save button can recapture a newly adjusted horizontal scale. This setting is persisted per symbol and timeframe.
