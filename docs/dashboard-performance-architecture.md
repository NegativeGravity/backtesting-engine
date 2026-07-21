# Dashboard Performance Architecture

VEX 1.2 treats the dashboard as a bounded, incremental rendering system rather than a conventional React page that reconstructs the whole replay state for every candle.

## Frame pipeline

```text
WebSocket frames
  -> adaptive scheduler
  -> merge until render deadline
  -> one React dispatch
  -> bounded replay state
  -> incremental chart update
  -> one browser paint
```

The scheduler uses three profiles:

- `smooth`: prioritizes animation continuity and low visual latency.
- `balanced`: default profile for normal replay.
- `throughput`: coalesces larger batches for high-speed backtests.

Hidden tabs are automatically throttled. Diagnostics are opt-in so FPS measurements and counters do not add overhead during ordinary use.

## Bounded state

- Visible candle state is capped at 12,000 bars per selected series.
- Strategy indicator series are capped at 12,000 points.
- The browser event window is capped at 5,000 records.
- Tables render bounded recent windows.
- Analytics SVG charts downsample large equity and drawdown arrays while preserving local extrema.

Immutable SQLite replay data remains the source of truth. Browser retention is only a viewport cache.

## Chart update rules

- New candles use the chart library's incremental `update` path.
- New indicator points use incremental updates.
- `setData` is reserved for reset, seek, timeframe replacement, and periodic compaction.
- Incoming bars are deduplicated by sequence.
- A fast append path avoids rebuilding maps when frames are strictly ordered.
- Full compaction occurs only after a large number of appends.

## Persistent viewport

Viewport state is persisted independently for each symbol and timeframe:

- visible candle count
- right offset
- follow-latest state
- horizontal scale lock
- vertical price range lock
- strategy-study visibility

A captured scale is not overwritten by replay updates. Users can operate the chart manually and save a new viewport at any time.

## React boundaries

High-frequency components are memoized. Stable callbacks prevent unrelated toolbar, inspector, metrics, and dock updates from invalidating the chart. Resizing is synchronized with `requestAnimationFrame`.

## Analytics charts

Equity and drawdown arrays may contain hundreds of thousands of points. The dashboard:

1. computes min/max iteratively without spreading large arrays,
2. downsamples to a bounded envelope,
3. preserves first, last, local minimum, and local maximum points,
4. generates bounded SVG paths.

This prevents call-stack failures and large DOM path costs on full-history analytics.
