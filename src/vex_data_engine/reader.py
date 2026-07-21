import csv
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa

from vex_contracts.data_engine import DataEngineConfig, DataQualityIssue
from vex_contracts.enums import DataIssueSeverity, TrailingBarPolicy
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.dialect import detect_csv_dialect
from vex_data_engine.models import ParsedFrame, StreamSummary

_BAR_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("timeframe", pa.string(), nullable=False),
        pa.field("open_time_ns", pa.int64(), nullable=False),
        pa.field("close_time_ns", pa.int64(), nullable=False),
        pa.field("open_ticks", pa.int64(), nullable=False),
        pa.field("high_ticks", pa.int64(), nullable=False),
        pa.field("low_ticks", pa.int64(), nullable=False),
        pa.field("close_ticks", pa.int64(), nullable=False),
        pa.field("tick_volume", pa.int64(), nullable=False),
        pa.field("real_volume", pa.int64(), nullable=False),
        pa.field("source_spread_points", pa.int32(), nullable=False),
        pa.field("sequence", pa.int64(), nullable=False),
        pa.field("source_row", pa.int64(), nullable=False),
        pa.field("is_complete", pa.bool_(), nullable=False),
    ]
)
_REQUIRED_COLUMNS = (
    "<DATE>",
    "<OPEN>",
    "<HIGH>",
    "<LOW>",
    "<CLOSE>",
    "<TICKVOL>",
    "<VOL>",
    "<SPREAD>",
)


def _issue(
    severity: DataIssueSeverity,
    code: str,
    message: str,
    row_number: int | None = None,
    **details: str | int | float | bool | None,
) -> DataQualityIssue:
    return DataQualityIssue(
        severity=severity,
        code=code,
        message=message,
        row_number=row_number,
        details=details,
    )


def _parse_scaled_integer(value: str, digits: int) -> int:
    text = value.strip()
    if not text:
        raise ValueError("empty decimal value")
    sign = -1 if text.startswith("-") else 1
    if text[0] in "+-":
        text = text[1:]
    whole, separator, fraction = text.partition(".")
    if not whole or not whole.isdigit() or (separator and not fraction.isdigit()):
        raise ValueError("invalid decimal value")
    if len(fraction) > digits:
        discarded = fraction[digits:]
        if any(character != "0" for character in discarded):
            raise ValueError("decimal value exceeds symbol precision")
        fraction = fraction[:digits]
    fraction = fraction.ljust(digits, "0")
    scaled = int(whole) * 10**digits + (int(fraction) if fraction else 0)
    return sign * scaled


def _parse_local_datetime(date_value: str, time_value: str) -> datetime:
    date_text = date_value.strip()
    time_text = time_value.strip()
    if len(date_text) != 10 or len(time_text) != 8:
        raise ValueError("invalid MT5 date or time width")
    return datetime(
        int(date_text[0:4]),
        int(date_text[5:7]),
        int(date_text[8:10]),
        int(time_text[0:2]),
        int(time_text[3:5]),
        int(time_text[6:8]),
    )


def _localize(naive: datetime, timezone: ZoneInfo) -> datetime:
    first = naive.replace(tzinfo=timezone, fold=0)
    second = naive.replace(tzinfo=timezone, fold=1)
    first_utc = first.astimezone(UTC)
    second_utc = second.astimezone(UTC)
    first_valid = first_utc.astimezone(timezone).replace(tzinfo=None) == naive
    second_valid = second_utc.astimezone(timezone).replace(tzinfo=None) == naive
    candidates = {
        candidate
        for candidate, valid in ((first_utc, first_valid), (second_utc, second_valid))
        if valid
    }
    if len(candidates) != 1:
        raise ValueError("ambiguous or nonexistent local timestamp")
    return candidates.pop()


def _to_ns(value: datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1000


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _close_time_ns(
    local_naive: datetime,
    open_time_ns: int,
    timeframe: Timeframe,
    timezone: ZoneInfo,
) -> int:
    if timeframe.seconds is not None and timeframe not in {Timeframe.D1, Timeframe.W1}:
        return open_time_ns + timeframe.seconds * 1_000_000_000
    if timeframe is Timeframe.D1:
        close_local = local_naive + timedelta(days=1)
    elif timeframe is Timeframe.W1:
        close_local = local_naive + timedelta(weeks=1)
    else:
        close_local = _next_month(local_naive)
    return _to_ns(_localize(close_local, timezone))


def _is_aligned(local_naive: datetime, timeframe: Timeframe) -> bool:
    if timeframe.seconds is None or timeframe is Timeframe.W1:
        return True
    epoch = datetime(1970, 1, 1)
    elapsed_seconds = int((local_naive - epoch).total_seconds())
    return elapsed_seconds % timeframe.seconds == 0


class Mt5CsvStream:
    def __init__(
        self,
        path: str | Path,
        symbol: str,
        timeframe: Timeframe,
        source_timezone: str,
        symbol_profile: SymbolProfile,
        completion_watermark: datetime,
        config: DataEngineConfig,
    ) -> None:
        self.path = Path(path)
        self.symbol = symbol
        self.timeframe = timeframe
        self.source_timezone = source_timezone
        self.symbol_profile = symbol_profile
        self.completion_watermark_ns = _to_ns(completion_watermark.astimezone(UTC))
        self.config = config
        self.dialect = detect_csv_dialect(self.path, timeframe)
        self.timezone = ZoneInfo(source_timezone)
        self.digits = int(symbol_profile.digits)
        self.tick_size_points = int(symbol_profile.trade_tick_size / symbol_profile.point)
        self._consumed = False
        self._finalized = False
        self._summary: StreamSummary | None = None
        self._source_rows = 0
        self._output_rows = 0
        self._complete_rows = 0
        self._incomplete_rows = 0
        self._detected_incomplete = 0
        self._invalid_parse = 0
        self._misaligned = 0
        self._negative = 0
        self._alignment = 0
        self._ohlc = 0
        self._duplicates = 0
        self._out_of_order = 0
        self._gaps = 0
        self._estimated_missing = 0
        self._maximum_gap_seconds = 0
        self._first_ns: int | None = None
        self._last_ns: int | None = None
        self._previous_ns: int | None = None
        self._sequence = 0
        self._conversion_error: str | None = None
        self._invalid_row_samples: list[int] = []
        self._columns: dict[str, list[object]] = self._new_columns()

    def __iter__(self) -> Iterator[object]:
        if self._consumed:
            raise RuntimeError("MT5 CSV streams can only be consumed once")
        self._consumed = True
        try:
            with self.path.open(
                "r",
                encoding=self.dialect.encoding,
                newline="",
                buffering=self.config.csv_block_size_bytes,
            ) as stream:
                reader = csv.reader(stream, delimiter=self.dialect.delimiter)
                header = next(reader, None)
                if header is None:
                    self._conversion_error = "CSV header is missing"
                else:
                    indexes = self._column_indexes(header)
                    for row_number, row in enumerate(reader, start=2):
                        self._source_rows += 1
                        self._consume_row(row, row_number, indexes)
                        if len(self._columns["open_time_ns"]) >= self.config.csv_batch_rows:
                            yield self._flush()
                    if self._columns["open_time_ns"]:
                        yield self._flush()
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            self._conversion_error = str(exc)[:1000]
        finally:
            self._finalize()

    def summary(self) -> StreamSummary:
        if not self._finalized or self._summary is None:
            raise RuntimeError("stream summary is available after full consumption")
        return self._summary

    def _column_indexes(self, header: list[str]) -> dict[str, int]:
        normalized = [value.strip() for value in header]
        required = [*_REQUIRED_COLUMNS]
        if self.dialect.has_time_column:
            required.append("<TIME>")
        missing = [column for column in required if column not in normalized]
        if missing:
            raise ValueError(f"missing required MT5 columns: {', '.join(missing)}")
        return {column: normalized.index(column) for column in required}

    def _consume_row(
        self,
        row: list[str],
        row_number: int,
        indexes: dict[str, int],
    ) -> None:
        try:
            date_value = row[indexes["<DATE>"]]
            time_value = row[indexes["<TIME>"]] if self.dialect.has_time_column else "00:00:00"
            local_naive = _parse_local_datetime(date_value, time_value)
            open_time_ns = _to_ns(_localize(local_naive, self.timezone))
            close_time_ns = _close_time_ns(
                local_naive,
                open_time_ns,
                self.timeframe,
                self.timezone,
            )
            point_values = tuple(
                _parse_scaled_integer(row[indexes[column]], self.digits)
                for column in ("<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>")
            )
            tick_volume = int(row[indexes["<TICKVOL>"]].strip())
            real_volume = int(row[indexes["<VOL>"]].strip())
            spread = int(row[indexes["<SPREAD>"]].strip())
        except (IndexError, TypeError, ValueError, OverflowError):
            self._invalid_parse += 1
            self._sample_invalid_row(row_number)
            return

        if any(value % self.tick_size_points for value in point_values):
            self._misaligned += 1
            return
        if tick_volume < 0 or real_volume < 0 or spread < 0:
            self._negative += 1
            return
        if not _is_aligned(local_naive, self.timeframe):
            self._alignment += 1
            return

        open_ticks, high_ticks, low_ticks, close_ticks = (
            value // self.tick_size_points for value in point_values
        )
        if high_ticks < max(open_ticks, close_ticks, low_ticks) or low_ticks > min(
            open_ticks,
            close_ticks,
            high_ticks,
        ):
            self._ohlc += 1
            return

        self._consume_timestamp(open_time_ns)
        is_complete = close_time_ns <= self.completion_watermark_ns
        if not is_complete:
            self._detected_incomplete += 1
            if self.config.trailing_bar_policy is TrailingBarPolicy.DROP:
                return

        self._append(
            row_number,
            open_time_ns,
            close_time_ns,
            open_ticks,
            high_ticks,
            low_ticks,
            close_ticks,
            tick_volume,
            real_volume,
            spread,
            is_complete,
        )

    def _consume_timestamp(self, open_time_ns: int) -> None:
        self._first_ns = (
            open_time_ns if self._first_ns is None else min(self._first_ns, open_time_ns)
        )
        self._last_ns = open_time_ns if self._last_ns is None else max(self._last_ns, open_time_ns)
        if self._previous_ns is not None:
            delta_ns = open_time_ns - self._previous_ns
            if delta_ns == 0:
                self._duplicates += 1
            elif delta_ns < 0:
                self._out_of_order += 1
            expected = self.timeframe.seconds
            if expected is not None:
                delta_seconds = delta_ns // 1_000_000_000
                if delta_seconds > expected:
                    self._gaps += 1
                    self._estimated_missing += delta_seconds // expected - 1
                    self._maximum_gap_seconds = max(
                        self._maximum_gap_seconds,
                        delta_seconds,
                    )
        self._previous_ns = open_time_ns

    def _append(
        self,
        row_number: int,
        open_time_ns: int,
        close_time_ns: int,
        open_ticks: int,
        high_ticks: int,
        low_ticks: int,
        close_ticks: int,
        tick_volume: int,
        real_volume: int,
        spread: int,
        is_complete: bool,
    ) -> None:
        values = {
            "open_time_ns": open_time_ns,
            "close_time_ns": close_time_ns,
            "open_ticks": open_ticks,
            "high_ticks": high_ticks,
            "low_ticks": low_ticks,
            "close_ticks": close_ticks,
            "tick_volume": tick_volume,
            "real_volume": real_volume,
            "source_spread_points": spread,
            "sequence": self._sequence,
            "source_row": row_number,
            "is_complete": is_complete,
        }
        for name, value in values.items():
            self._columns[name].append(value)
        self._sequence += 1
        self._output_rows += 1
        if is_complete:
            self._complete_rows += 1
        else:
            self._incomplete_rows += 1

    def _flush(self) -> object:
        row_count = len(self._columns["open_time_ns"])
        data = {
            "symbol": [self.symbol] * row_count,
            "timeframe": [self.timeframe.value] * row_count,
            **self._columns,
        }
        batch = pa.RecordBatch.from_pydict(data, schema=_BAR_SCHEMA)
        self._columns = self._new_columns()
        return batch

    def _sample_invalid_row(self, row_number: int) -> None:
        if len(self._invalid_row_samples) < self.config.max_issue_samples:
            self._invalid_row_samples.append(row_number)

    def _new_columns(self) -> dict[str, list[object]]:
        return {
            "open_time_ns": [],
            "close_time_ns": [],
            "open_ticks": [],
            "high_ticks": [],
            "low_ticks": [],
            "close_ticks": [],
            "tick_volume": [],
            "real_volume": [],
            "source_spread_points": [],
            "sequence": [],
            "source_row": [],
            "is_complete": [],
        }

    def _finalize(self) -> None:
        if self._finalized:
            return
        issues: list[DataQualityIssue] = []
        if self._conversion_error is not None:
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "CSV_CONVERSION_FAILED",
                    self._conversion_error,
                )
            )
        if self._source_rows == 0:
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "EMPTY_SOURCE_FILE",
                    "CSV file contains no data rows",
                )
            )
        if self._invalid_parse:
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "VALUE_PARSE_FAILED",
                    "one or more CSV values could not be parsed without loss",
                    count=self._invalid_parse,
                )
            )
            issues.extend(
                _issue(
                    DataIssueSeverity.ERROR,
                    "VALUE_PARSE_FAILED_ROW",
                    "CSV row contains an invalid value",
                    row_number=row_number,
                )
                for row_number in self._invalid_row_samples
            )
        counters = (
            (
                self._misaligned,
                "PRICE_NOT_TICK_ALIGNED",
                "one or more prices are not aligned to the symbol tick size",
            ),
            (
                self._negative,
                "NEGATIVE_MARKET_VALUE",
                "volume and spread values must be non-negative",
            ),
            (
                self._alignment,
                "TIMEFRAME_ALIGNMENT_FAILED",
                "bar open timestamps are not aligned to the declared timeframe",
            ),
            (
                self._ohlc,
                "OHLC_INVARIANT_FAILED",
                "one or more rows contain inconsistent OHLC prices",
            ),
            (
                self._duplicates,
                "DUPLICATE_TIMESTAMP",
                "duplicate bar open timestamps were found",
            ),
            (
                self._out_of_order,
                "OUT_OF_ORDER_TIMESTAMP",
                "bar timestamps are not monotonically increasing",
            ),
        )
        issues.extend(
            _issue(DataIssueSeverity.ERROR, code, message, count=count)
            for count, code, message in counters
            if count
        )
        if self._gaps:
            issues.append(
                _issue(
                    DataIssueSeverity.INFO,
                    "TIMESTAMP_GAPS_DETECTED",
                    "timestamp gaps were detected and retained",
                    count=self._gaps,
                    estimated_missing_bars=self._estimated_missing,
                    maximum_gap_seconds=self._maximum_gap_seconds,
                )
            )
        if self._detected_incomplete:
            severity = (
                DataIssueSeverity.ERROR
                if self.config.trailing_bar_policy is TrailingBarPolicy.REJECT
                else DataIssueSeverity.INFO
            )
            issues.append(
                _issue(
                    severity,
                    "TRAILING_INCOMPLETE_BAR",
                    "trailing bars extend beyond the completion watermark",
                    count=self._detected_incomplete,
                )
            )
        self._summary = StreamSummary(
            source_row_count=self._source_rows,
            output_row_count=self._output_rows,
            complete_row_count=self._complete_rows,
            incomplete_row_count=self._incomplete_rows,
            delimiter=self.dialect.delimiter,
            issues=tuple(issues),
            duplicate_timestamp_count=self._duplicates,
            out_of_order_count=self._out_of_order,
            gap_count=self._gaps,
            estimated_missing_bars=self._estimated_missing,
            maximum_gap_seconds=self._maximum_gap_seconds,
            actual_start_ns=self._first_ns,
            actual_end_ns=self._last_ns,
        )
        self._finalized = True


def read_mt5_csv(
    path: str | Path,
    symbol: str,
    timeframe: Timeframe,
    source_timezone: str,
    symbol_profile: SymbolProfile,
    completion_watermark: datetime,
    config: DataEngineConfig,
) -> ParsedFrame:
    import polars as pl

    stream = Mt5CsvStream(
        path,
        symbol,
        timeframe,
        source_timezone,
        symbol_profile,
        completion_watermark,
        config,
    )
    frames: list[pl.DataFrame] = []
    for batch in stream:
        converted = pl.from_arrow(batch)
        if not isinstance(converted, pl.DataFrame):
            raise TypeError("Arrow record batch did not produce a DataFrame")
        frames.append(converted)
    summary = stream.summary()
    frame = pl.concat(frames, how="vertical", rechunk=False) if frames else pl.DataFrame()
    return ParsedFrame(
        frame=frame,
        source_row_count=summary.source_row_count,
        delimiter=summary.delimiter,
        issues=summary.issues,
        duplicate_timestamp_count=summary.duplicate_timestamp_count,
        out_of_order_count=summary.out_of_order_count,
        gap_count=summary.gap_count,
        estimated_missing_bars=summary.estimated_missing_bars,
        maximum_gap_seconds=summary.maximum_gap_seconds,
    )
