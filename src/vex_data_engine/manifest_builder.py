from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

from vex_contracts.dataset import DatasetFile, DatasetManifest
from vex_contracts.enums import DatasetSource, PriceBasis
from vex_data_engine.discovery import discover_mt5_files
from vex_data_engine.hashing import sha256_file
from vex_data_engine.inspection import read_last_open_time


def build_manifest(
    root: str | Path,
    dataset_id: str,
    version: str,
    name: str,
    source_timezone: str,
    repository_root: str | Path,
) -> DatasetManifest:
    repository = Path(repository_root).resolve()
    data_root = Path(root).resolve()
    relative_root = data_root.relative_to(repository).as_posix()
    zone = ZoneInfo(source_timezone)
    files = []
    for discovered in discover_mt5_files(data_root):
        declared_start = discovered.declared_start_local.replace(tzinfo=zone).astimezone(UTC)
        declared_end = read_last_open_time(
            discovered.path,
            discovered.timeframe,
            source_timezone,
        )
        row_count = _count_data_rows(discovered.path)
        files.append(
            DatasetFile(
                symbol=discovered.symbol,
                timeframe=discovered.timeframe,
                relative_path=discovered.path.relative_to(data_root).as_posix(),
                declared_start=declared_start,
                declared_end=declared_end,
                row_count=row_count,
                size_bytes=discovered.path.stat().st_size,
                sha256=sha256_file(discovered.path),
            )
        )
    return DatasetManifest(
        dataset_id=dataset_id,
        version=version,
        name=name,
        source=DatasetSource.MT5_CSV,
        root_path=relative_root,
        price_basis=PriceBasis.BID,
        source_timezone=source_timezone,
        files=tuple(files),
    )


def _count_data_rows(path: Path) -> int:
    with path.open("rb") as stream:
        return max(sum(1 for line in stream if line.strip()) - 1, 0)
