# ADR 0023 — Server-Driven Deterministic Replay

## Status

Accepted

## Context

Browser timers are not reliable enough to define financial replay ordering. Different devices and rendering loads would otherwise produce different event timing and state transitions.

## Decision

The server owns the replay cursor and applies commands against the immutable execution-bar sequence. Forward movement emits delta frames. Backward movement and seeking emit reconstructed bootstrap state.

## Consequences

- Replay behavior is independent of browser frame rate.
- All clients observe the same cursor sequence.
- Playback can be paused, resumed, and sought without mutating the underlying run.
- WebSocket transport remains a presentation mechanism rather than the source of truth.
