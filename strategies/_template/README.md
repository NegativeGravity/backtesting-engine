# Replace Me Strategy

1. Copy this directory to `strategies/<package_id>`.
2. Rename identifiers in `package.yaml`, `strategy.yaml`, and `run.yaml`.
3. Update `strategy.yaml` entrypoint to `<package_id>.strategy:<ClassName>`.
4. Implement callbacks in `strategy.py`.
5. Keep `enabled: false` until all files validate, then set it to `true`.
6. Refresh the running engine with `scripts/strategy-refresh.ps1`.
7. Create a paused run with `scripts/run-strategy.ps1`.
8. Advance with `step_forward` or use Dashboard Live mode.

Use `context.market` for visible history, `context.orders` for broker actions, `context.chart` for indicators and drawings, `context.portfolio` for read-only state, and `context.log` for structured diagnostics.
