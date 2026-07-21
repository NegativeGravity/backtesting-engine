# System Context

```mermaid
flowchart LR
    UI[Dashboard Web]
    API[Backtest API]
    Worker[Backtest Worker]
    Strategy[Strategy Process]
    Data[MT5 Data Engine]
    Store[(PostgreSQL and Artifacts)]
    Redis[(Redis)]
    MT5[Future MT5 Bridge]

    UI --> API
    UI <--> API
    API --> Redis
    Worker --> Redis
    Worker <--> Strategy
    Worker --> Data
    Worker --> Store
    API --> Store
    MT5 --> API
```

## Contract Ownership

```mermaid
flowchart TD
    Contracts[Vex Contracts]
    Contracts --> API
    Contracts --> Worker
    Contracts --> Strategy
    Contracts --> Data
    Contracts --> UI
    Contracts --> MT5
```

The contracts package contains transport and domain boundaries only. It does not contain database access, HTTP handlers, strategy logic, chart vendor adapters, or broker simulation behavior.
