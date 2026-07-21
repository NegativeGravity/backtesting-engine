# Order Lifecycle Contract

Orders start in `created` and advance only through allowed state transitions.

## Terminal States

- Filled
- Cancelled
- Rejected
- Expired

## Revisions

Every transition and fill increments the order revision. Consumers can reject stale updates by revision.

## Fills

Fills carry price ticks, lot volume, commission, spread cost, and slippage cost. Average fill price is stored in decimal ticks to preserve weighted averages.
