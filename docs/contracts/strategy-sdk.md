# Strategy SDK Contract

## Entrypoint

A strategy descriptor resolves an importable class through `module:object` syntax. The object must subclass `vex_strategy.Strategy`.

```yaml
entrypoint: my_strategies.breakout:BreakoutStrategy
```

## Parameters

A strategy declares a frozen Pydantic parameter model.

```python
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from vex_strategy import Strategy


class BreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lookback: int = Field(default=20, ge=2)


class BreakoutStrategy(Strategy):
    parameter_model: ClassVar[type[BaseModel]] = BreakoutParameters
```

Unknown parameters fail before the first callback.

## Lifecycle

```python
class Strategy:
    def on_start(self, context: StrategyContext) -> None:
        ...

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        ...

    def on_order_update(self, context: StrategyContext, event: EventEnvelope) -> None:
        ...

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        ...
```

`on_stop` cannot emit order actions. Chart commands and logs remain valid.

## Market Access

```python
latest = context.market.latest("XAUUSD", Timeframe.M5)
history = context.market.history("XAUUSD", Timeframe.H1, 100)
forming = context.market.forming("XAUUSD", Timeframe.H4)
```

`forming` is available only when the subscription uses `forming_allowed`. Historical windows contain closed bars only and are bounded by the configured per-series history limit.

## Portfolio Access

```python
account = context.portfolio.account
positions = context.portfolio.positions(symbol="XAUUSD")
orders = context.portfolio.orders(symbol="XAUUSD")
last_trade = context.portfolio.last_trade("XAUUSD")
```

Views are immutable snapshots updated by the parent worker.

## Order Actions

```python
context.orders.buy_market(
    "XAUUSD",
    volume_lots="0.10",
    stop_loss_ticks=260000,
    take_profit_ticks=262000,
)

context.orders.limit(
    "XAUUSD",
    Side.BUY,
    price_ticks=260500,
    volume_lots="0.10",
)

context.orders.close_position(position_id)
context.orders.cancel(order_id)
context.orders.modify_protection(position_id, 260100, 262500)
```

The SDK emits intents. The broker simulator remains responsible for validation, normalization, margin, spread, commission, slippage, order state, and fills.

When `volume_lots` is omitted, the default run sizing model is used. Risk-based sizing requires an entry reference and an appropriate stop.

## Chart Commands

```python
context.chart.declare_pane("momentum", "Momentum")
context.chart.declare_series("rsi", "momentum", "RSI")
context.chart.plot_scalar("rsi", 54.2)
context.chart.trend_line(...)
context.chart.rectangle(...)
context.chart.marker(...)
context.chart.risk_reward(...)
```

Drawing IDs are stable. Repeated upserts increment revisions. Strategies do not import TradingView APIs.

## Structured Logs

```python
context.log.info("breakout_detected", price_ticks=261250)
```

Fields must be scalar JSON values.
