from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vex_contracts.timeframes import Timeframe
from vex_data_engine.dialect import detect_csv_dialect


def read_last_open_time(
    path: str | Path,
    timeframe: Timeframe,
    source_timezone: str,
) -> datetime:
    source = Path(path)
    dialect = detect_csv_dialect(source, timeframe)
    with source.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        buffer = bytearray()
        while position > 0:
            position -= 1
            stream.seek(position)
            byte = stream.read(1)
            if byte in {b"\n", b"\r"}:
                if buffer:
                    break
                continue
            buffer.extend(byte)
    line = bytes(reversed(buffer)).decode("utf-8-sig").strip()
    values = line.split(dialect.delimiter)
    columns = list(dialect.columns)
    date_value = values[columns.index("<DATE>")]
    time_value = values[columns.index("<TIME>")] if dialect.has_time_column else "00:00:00"
    local_time = datetime.strptime(f"{date_value} {time_value}", "%Y.%m.%d %H:%M:%S")
    return local_time.replace(tzinfo=ZoneInfo(source_timezone)).astimezone(UTC)
