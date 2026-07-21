import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter


def canonical_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return TypeAdapter(type(value)).dump_python(value, mode="json", exclude_none=True)


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_data(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_yaml(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def dump_yaml(value: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            canonical_data(value),
            stream,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def dump_json(value: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(
            canonical_data(value),
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
