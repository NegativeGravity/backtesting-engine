from pathlib import Path

from vex_contracts.timeframes import Timeframe
from vex_data_engine.exceptions import DataSchemaError
from vex_data_engine.models import CsvDialect

_REQUIRED_PRICE_COLUMNS = ("<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>")
_REQUIRED_VOLUME_COLUMNS = ("<TICKVOL>", "<VOL>", "<SPREAD>")
_SUPPORTED_DELIMITERS = ("\t", ",", ";", "|")


def detect_csv_dialect(path: str | Path, timeframe: Timeframe) -> CsvDialect:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        header = stream.readline().strip("\r\n")
    if not header:
        raise DataSchemaError(f"empty CSV header: {source}")
    delimiter = max(_SUPPORTED_DELIMITERS, key=header.count)
    if header.count(delimiter) == 0:
        raise DataSchemaError(f"unable to detect CSV delimiter: {source}")
    columns = tuple(part.strip().upper() for part in header.split(delimiter))
    required = {"<DATE>", *_REQUIRED_PRICE_COLUMNS, *_REQUIRED_VOLUME_COLUMNS}
    if timeframe is not Timeframe.D1:
        required.add("<TIME>")
    missing = sorted(required.difference(columns))
    if missing:
        raise DataSchemaError(f"missing columns in {source.name}: {', '.join(missing)}")
    duplicates = sorted({column for column in columns if columns.count(column) > 1})
    if duplicates:
        raise DataSchemaError(f"duplicate columns in {source.name}: {', '.join(duplicates)}")
    allowed = required | ({"<TIME>"} if timeframe is Timeframe.D1 else set())
    unknown = sorted(set(columns).difference(allowed))
    if unknown:
        raise DataSchemaError(f"unknown columns in {source.name}: {', '.join(unknown)}")
    return CsvDialect(
        delimiter=delimiter,
        columns=columns,
        has_time_column="<TIME>" in columns,
        encoding="utf-8-sig",
    )
