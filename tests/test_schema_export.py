import json
from pathlib import Path

from vex_contracts.registry import contract_kinds
from vex_contracts.schema_export import export_schemas


def test_schema_export_writes_every_contract(tmp_path: Path) -> None:
    paths = export_schemas(tmp_path)

    assert len(paths) == len(contract_kinds())
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert path.name.endswith(".schema.json")
