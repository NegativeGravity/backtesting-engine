# Rule-to-code traceability

| Transcript section | Mechanical rule | Implementation |
|---|---|---|
| 03:16–04:01 | M15 LS plus opposite-sign 2m Volume Delta | `Candle.long_ls`, `Candle.short_ls`, `ClockAlignedM2Delta` |
| 05:26–06:40 | Bull→Bear high, Bear→Bull low, strict hunt | `SignalEngine._detect_new_structure`, `StructureLevel.strict_hunt` |
| 07:08–08:04 | Only last three structures; body-close invalidation | `SignalEngine._active`, `_invalidate_after_signal` |
| 08:27–08:51 | Signal candle may trade the level it breaks | evaluation precedes invalidation |
| 08:58–09:20 | Intervening higher/lower wick must also be swept | `intervening_extreme_ticks` |
| 09:43–12:37 | Main 2R, cover at main SL, cover stop behind body, 1R, strict equality | broker execution/stop-and-reverse tags |
| 13:37–16:58 | Engulf colors, new session extreme, previous-body sweep, Delta | `SignalEngine.evaluate` engulf branch |
| 15:34–15:50 | LS+Engulf opens one position | `SetupKind.LS_ENGULF`, one returned `Signal` |
| 18:57–20:18 | +6 before day 15 pause; continue to +8 | `RiskGovernor.permission` |
| 26:14–27:37 | Enter on confirmed M15 close; close at chart target | next M1 open execution, broker TP |
| 28:22–29:17 | 5 positions incl. cover, -4 daily, ±8 monthly, -7 pause, 2 primary TPs/day | `RiskGovernor` |

The source transcript is included at `references/video-transcript-fa.txt`.
