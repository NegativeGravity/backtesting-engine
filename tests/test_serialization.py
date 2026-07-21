from pathlib import Path

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import canonical_json, fingerprint, load_yaml


def test_fingerprint_is_deterministic(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/run.yaml")
    first = BacktestRunConfig.model_validate(payload)
    second = BacktestRunConfig.model_validate(payload)

    assert canonical_json(first) == canonical_json(second)
    assert fingerprint(first) == fingerprint(second)
    assert len(fingerprint(first)) == 64
