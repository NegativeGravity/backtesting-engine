# YJ Notebook Parity Audit

Reference: `yj-strategy(1).ipynb`, SHA-256 `cd2439ebdfa813c9c52d0b528f21a81c03d6ee31c856e8f67215b4087039fc23`.

| Notebook behavior | VEX 1.2.0 implementation |
|---|---|
| Use MT5 `<DATE>` and `<TIME>` exactly as stored | Dataset v2 maps stored wall clock to `Asia/Tehran`; raw 01:30 round-trips to strategy 01:30 |
| Eight M15 bars from 01:30 through 03:15 | Exact minute set and strict count validation |
| First valid break after 03:30 | OCO stop pair activates on next 03:30 bar |
| Open above high / below low fills at open | `marketable_open` gap policy and execution-time R recalculation |
| Inside-open candle touches both boundaries | OCO `cancel_all`; no trade for the day |
| Risk 1% current balance | Risk-percent sizing while flat; equity equals balance |
| Target 1.5R from actual entry to opposite box edge stop | Execution risk/reward tag recalculates target after gap fill |
| Stop before target on ambiguous exit bar | Conservative intrabar policy |
| Initial target may occur on entry candle | Same-bar exit enabled and target-only intrabar entry allowed |
| Initial stop creates one opposite reversal | Broker stop-and-reverse at stop fill price |
| Reversal uses updated balance | Account revalued before reversal sizing |
| Reversal cannot exit on its creation candle | Reversal extrema deferred to next M15 bar |
| No third leg | Generated reversal has no further stop-and-reverse instruction |
| Untriggered day expires at midnight | DAY order expiry at next Tehran midnight |
| Existing position delays a new day's entry | Require-flat pending pair and same-bar re-evaluation after flat |
| Remaining position closes at final available close | End-of-data liquidation enabled |
| `DROP_LAST_BAR=True` | Run end is exclusive at the last raw bar's close, excluding the final 13:15 row |
| Daily box remains inspectable | Completed box metadata retained, viewport-indexed, and re-upserted on position open/close |

Focused parity tests cover long/short gaps, OCO ambiguity, deferred entry, stop priority, same-bar target, reversal sizing and timing, and prevention of a third leg.
