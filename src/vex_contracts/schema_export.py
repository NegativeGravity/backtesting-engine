import json
from pathlib import Path

from vex_contracts.registry import contract_kinds, contract_schema


def export_schemas(output: str | Path) -> tuple[Path, ...]:
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for kind in contract_kinds():
        target = output_path / f"{kind}.schema.json"
        with target.open("w", encoding="utf-8") as stream:
            json.dump(contract_schema(kind), stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        written.append(target)
    return tuple(written)
