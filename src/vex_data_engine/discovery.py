import re
from datetime import datetime
from pathlib import Path

from vex_contracts.timeframes import Timeframe
from vex_data_engine.exceptions import DataDiscoveryError
from vex_data_engine.models import ParsedMt5Filename

_TIMEFRAME_ALIASES = {
    "DAILY": Timeframe.D1,
    "DAY": Timeframe.D1,
    "D1": Timeframe.D1,
}
for _timeframe in Timeframe:
    _TIMEFRAME_ALIASES.setdefault(_timeframe.value.upper(), _timeframe)

_TIMEFRAME_PATTERN = "|".join(
    sorted((re.escape(value) for value in _TIMEFRAME_ALIASES), key=len, reverse=True)
)
_FILENAME_PATTERN = re.compile(
    rf"^(?P<symbol>.+)_(?P<timeframe>{_TIMEFRAME_PATTERN})_"
    r"(?P<start>\d{12})_(?P<end>\d{12})(?:\(\d+\))?\.csv$",
    re.IGNORECASE,
)


def parse_mt5_filename(path: str | Path) -> ParsedMt5Filename:
    resolved = Path(path)
    match = _FILENAME_PATTERN.fullmatch(resolved.name)
    if match is None:
        raise DataDiscoveryError(f"unsupported MT5 filename: {resolved.name}")
    symbol = match.group("symbol").upper()
    timeframe = _TIMEFRAME_ALIASES[match.group("timeframe").upper()]
    declared_start = datetime.strptime(match.group("start"), "%Y%m%d%H%M")
    declared_end = datetime.strptime(match.group("end"), "%Y%m%d%H%M")
    if declared_start > declared_end:
        raise DataDiscoveryError(f"filename start exceeds end: {resolved.name}")
    canonical_name = f"{symbol}_{timeframe.value}_{match.group('start')}_{match.group('end')}.csv"
    return ParsedMt5Filename(
        path=resolved,
        symbol=symbol,
        timeframe=timeframe,
        declared_start_local=declared_start,
        declared_end_local=declared_end,
        canonical_name=canonical_name,
    )


def discover_mt5_files(root: str | Path, recursive: bool = False) -> tuple[ParsedMt5Filename, ...]:
    directory = Path(root)
    if not directory.exists():
        raise DataDiscoveryError(f"data directory does not exist: {directory}")
    if not directory.is_dir():
        raise DataDiscoveryError(f"data root is not a directory: {directory}")
    candidates = directory.rglob("*.csv") if recursive else directory.glob("*.csv")
    discovered: list[ParsedMt5Filename] = []
    invalid: list[str] = []
    for path in sorted(candidates, key=lambda item: item.as_posix().lower()):
        try:
            discovered.append(parse_mt5_filename(path))
        except DataDiscoveryError:
            invalid.append(path.name)
    if invalid:
        names = ", ".join(invalid)
        raise DataDiscoveryError(f"unrecognized CSV files found: {names}")
    if not discovered:
        raise DataDiscoveryError(f"no MT5 CSV files found in {directory}")
    keys = [(item.symbol, item.timeframe) for item in discovered]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        formatted = ", ".join(f"{symbol}:{timeframe.value}" for symbol, timeframe in duplicates)
        raise DataDiscoveryError(f"duplicate symbol/timeframe files found: {formatted}")
    return tuple(discovered)
