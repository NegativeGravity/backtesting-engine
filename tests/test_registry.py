from pathlib import Path

from vex_contracts.registry import contract_kinds, contract_schema, validate_contract
from vex_contracts.serialization import load_yaml


def test_registry_validates_all_primary_examples(project_root: Path) -> None:
    examples = {
        "dataset-manifest": "dataset.template.yaml",
        "symbol-profile": "symbol_xauusd.yaml",
        "strategy-descriptor": "strategy.yaml",
        "run-config": "run.yaml",
        "order-request": "order_request.yaml",
        "chart-command": "chart_command.yaml",
    }

    for kind, filename in examples.items():
        model = validate_contract(kind, load_yaml(project_root / "examples/configs" / filename))
        assert model is not None


def test_registry_exports_json_schemas() -> None:
    for kind in contract_kinds():
        schema = contract_schema(kind)
        assert "$defs" in schema or "properties" in schema or "oneOf" in schema
