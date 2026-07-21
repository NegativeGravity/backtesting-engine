# Vex Replay Dashboard

React and TypeScript replay workspace for deterministic MT5 candle backtests.

## Development

```powershell
npm ci
npm run dev
```

The Vite development server proxies REST and WebSocket traffic to the dashboard gateway on `127.0.0.1:8000`; start the engine and gateway first with `scripts/dashboard-dev.ps1` or the separate service scripts.

## Production Build

```powershell
npm run check
```

The dashboard FastAPI gateway serves the generated `dist` directory and proxies REST and WebSocket traffic to the independently running backtest engine.

## Chart Integration

`LightweightChartsAdapter` is the default adapter. `AdvancedChartsAdapter` is a boundary for a separately licensed TradingView Advanced Charts package. Strategy code emits vendor-neutral chart commands and never imports a chart vendor API.
