# Chart Protocol Contract

The protocol separates strategy visualization from dashboard rendering.

## Layers

Every strategy owns one or more layers. A layer can be cleared without affecting market data or another strategy.

## Objects

Every drawing has a stable ID and revision. Upsert operations create a missing object or replace an older revision.

## Replay

Chart commands can be persisted in event order. The dashboard can rebuild chart state from the nearest snapshot and subsequent commands.
