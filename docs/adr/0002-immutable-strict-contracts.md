# ADR 0002: Immutable Strict Contracts

## Status

Accepted

## Decision

Use immutable Pydantic v2 models with forbidden extra fields for all public contracts.

## Rationale

Backtests must be reproducible. Silent field acceptance, runtime mutation, and weak coercion create undetectable configuration drift.

## Consequences

- Unknown fields fail validation.
- Changes create new model instances.
- Cross-field invariants live next to the contract.
- Transport schemas are generated directly from validated models.
