# LS + 2m Volume Delta for VEX

## Source-derived rules

The package implements the mechanical rules in the supplied Pine script and transcript:

- US30USD / Dow Jones, M15.
- Trade window: 12:00 through 19:30 in the configured session timezone.
- LS geometry exactly follows the Pine inequalities.
- A short requires positive two-minute Volume Delta.
- A long requires negative two-minute Volume Delta.
- A swing high is a bullish candle followed by a bearish candle.
- A swing low is a bearish candle followed by a bullish candle.
- Only the latest three formed highs and the latest three formed lows are in scope; invalid ones inside that fixed three-level window are skipped, and older levels never resurrect.
- A high becomes invalid after a later candle closes above the higher body edge of its two forming candles.
- A low becomes invalid after a later candle closes below the lower body edge.
- A signal candle may trade the level it invalidates; invalidation applies after that candle is evaluated.
- A hunt is strict. Equality is not a hunt.
- The signal must also exceed every intervening wick between the structure and the signal.
- Engulf does not require a swing structure.
- Short engulf: previous candle bullish, signal bearish, signal is a strict new session high, and its wick strictly exceeds the previous bullish body high.
- Long engulf: previous candle bearish, signal bullish, signal is a strict new session low, and its wick strictly exceeds the previous bearish body low to the downside.
- If LS and engulf occur together, only one primary trade opens.
- Primary entry is represented by the next M1 open after the M15 close.
- Primary stop is behind the signal wick and target is 2R.
- Cover is an automatic stop-and-reverse at the primary stop, with its stop behind the signal body and target 1R.
- A cover counts toward the five-position daily limit.
- Two primary TPs stop trading for the day.
- Daily realized limit is -4R.
- Monthly pause is +6R before day 15, then trading resumes from day 15 toward +8R.
- Monthly limits are +8R and -8R.
- At -7R the strategy pauses for the rest of that calendar day; a cover is not armed when the primary stop itself would take the month to -7R.

## Volume Delta

The engine builds clock-aligned, fully closed M2 bars from M1 data from the same price/volume feed. Each M2 bar's entire tick volume is signed by its candle direction. A doji uses its close relative to the previous M2 close and then the previous direction if unchanged. Only fully closed M2 bars inside the M15 signal candle are used. Seven bars are normally available because 15 minutes is not divisible by two.

Exact TradingView signal parity requires OANDA US30USD M1 volume. MT5 tick volume is supported as a documented proxy but can change Delta signs.

This is causal and prevents a 12:14–12:16 M2 candle from leaking the 12:15–12:16 minute into a signal decided at 12:15.

## Replay output

The chart remains intentionally sparse:

- one low-opacity session range;
- one marker only for an executable LS/Engulf + Delta setup;
- one dashed hunted-structure line only when it caused an LS trade;
- one dotted cover-entry line only when cover is enabled;
- broker-authoritative risk/reward boxes and entry/exit markers.

Set `draw_raw_confirmations: true` only for diagnostics. Early-warning alerts from the Pine script are intentionally excluded because a deterministic backtest only acts on confirmed M15 closes.

## Required data

The package expects M1 and M15 MT5 CSV data for your broker's US30USD symbol. The included symbol profile is a placeholder. Replace it with a profile generated and verified by the VEX MT5 compatibility bootstrap.

Keep `package.yaml` disabled until:

1. `dataset.yaml` is generated with real file metadata.
2. `symbol_us30usd.yaml` is replaced with the verified broker profile.
3. the Data Engine import report exists.

## Installation

Copy the package into `strategies/ls_volume_delta`, add the tests, prepare the real dataset and profile, then enable `package.yaml`.

The installer performs source checks and never overwrites a verified symbol profile unless explicitly requested.


## Explicit deterministic interpretations

The transcript does not completely specify every execution edge. The package therefore records these decisions instead of hiding them:

- `Asia/Tehran` is the default timezone for the stated 12:00–19:30 window and is configurable.
- One active primary/cover chain is allowed at a time.
- Risk gates use nominal strategy R by default (`+2`, `-1`, `+1`, `-1`); set `risk_accounting_mode: broker_realized` for cost-adjusted R.
- If only one of the five daily position slots remains, the final primary may be taken without arming cover.
- M1 conservative intrabar resolution is deterministic but cannot reproduce the one-second ordering shown in the video when both levels are touched inside one M1 candle. Exact ordering needs S1/tick data.
