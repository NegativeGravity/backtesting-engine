# ADR 0020: Windows Spawn Strategy Isolation

## Status

Accepted.

## Decision

Each strategy instance runs in a persistent Python process created with the multiprocessing `spawn` context. The worker owns the strategy object and its mutable state. The parent owns market ingestion, broker state, event ordering, persistence, and output application.

The process host enforces startup, callback, and shutdown timeouts. Callback exceptions and worker termination are propagated to the parent. The phase does not claim operating-system security sandboxing.

## Consequences

- The runtime behaves consistently on Windows and Linux.
- A strategy crash does not corrupt the broker process.
- Strategy entrypoints and IPC payloads must be importable and serializable.
- Network, filesystem, CPU, and memory sandboxing remain deployment responsibilities.
