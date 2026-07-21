# ADR 0030 — Host-side MT5 Bridge

## Status

Accepted

## Decision

The MT5 compatibility collector runs on the Windows host and writes immutable JSON snapshots consumed by the containerized platform.

The Linux application containers do not attempt to install or automate the MetaTrader terminal.

## Consequences

- MT5 terminal compatibility remains explicit and testable.
- Docker deployment stays portable and deterministic.
- Credentials remain on the Windows host.
- The application can validate historical runs without a live terminal.
- Live order routing remains a separate future service.
