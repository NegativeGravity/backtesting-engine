# Event Envelope Contract

The event envelope is the transport and replay boundary.

## Ordering

`sequence` defines total order inside a run. `event_time_ns` defines market chronology. `emitted_at` is operational metadata.

## Diagnostics

`correlation_id` connects related operations. `causation_id` points to the event that directly caused the current event.

## Compatibility

Readers must reject unsupported schema versions instead of silently interpreting changed payload semantics.
