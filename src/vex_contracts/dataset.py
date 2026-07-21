from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, PositiveInt, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import DatasetSource, PriceBasis
from vex_contracts.identifiers import Identifier, Sha256Hex, SymbolCode
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class DatasetFile(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    relative_path: str = Field(min_length=1, max_length=512)
    declared_start: AwareDatetime | None = None
    declared_end: AwareDatetime | None = None
    actual_start: AwareDatetime | None = None
    actual_end: AwareDatetime | None = None
    row_count: PositiveInt | None = None
    size_bytes: PositiveInt | None = None
    sha256: Sha256Hex | None = None

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("relative_path must remain inside the dataset root")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_ranges(self) -> "DatasetFile":
        pairs = (
            (self.declared_start, self.declared_end, "declared"),
            (self.actual_start, self.actual_end, "actual"),
        )
        for start, end, label in pairs:
            if (start is None) != (end is None):
                raise ValueError(f"{label}_start and {label}_end must be provided together")
            if start is not None and end is not None and start >= end:
                raise ValueError(f"{label}_start must be earlier than {label}_end")
        return self


class DatasetManifest(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    dataset_id: Identifier
    version: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    source: Literal[DatasetSource.MT5_CSV] = DatasetSource.MT5_CSV
    root_path: str = Field(min_length=1, max_length=512)
    price_basis: PriceBasis = PriceBasis.BID
    source_timezone: str = Field(min_length=1, max_length=128)
    engine_timezone: Literal["UTC"] = "UTC"
    files: tuple[DatasetFile, ...] = Field(min_length=1)
    content_hash: Sha256Hex | None = None
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("root_path")
    @classmethod
    def validate_root_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("root_path must be repository-relative")
        return path.as_posix()

    @field_validator("source_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("source_timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_files(self) -> "DatasetManifest":
        keys = [(item.symbol, item.timeframe) for item in self.files]
        if len(keys) != len(set(keys)):
            raise ValueError("files must contain one entry per symbol and timeframe")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("files must use unique relative paths")
        return self
