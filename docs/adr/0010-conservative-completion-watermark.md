# ADR 0010: Conservative Completion Watermark

## Status

Accepted

## Decision

A bar is closed only when its close timestamp is not later than the dataset completion watermark. Without an explicit as-of time, the watermark is inferred from the final open timestamp of the finest fixed-duration source.

## Consequences

The final bar of each supplied timeframe is conservatively treated as incomplete. Users can provide an explicit as-of time when export completion is independently known.
