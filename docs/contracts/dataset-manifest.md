# Dataset Manifest Contract

The manifest is the authoritative catalog entry for one immutable dataset version.

## File Identity

Each symbol-timeframe pair appears once. Every file path is relative to the dataset root and cannot escape it.

## Time

Source timezone is an IANA timezone. Engine timezone is UTC. Declared and actual ranges are stored as timezone-aware datetimes.

## Integrity

Phase 1 populates row counts, byte sizes, SHA-256 values, actual ranges, and the dataset content hash.
