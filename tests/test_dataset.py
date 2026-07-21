from pathlib import Path

import pytest
from pydantic import ValidationError

from vex_contracts.dataset import DatasetManifest
from vex_contracts.serialization import load_yaml


def test_example_dataset_manifest_is_valid(project_root: Path) -> None:
    manifest = DatasetManifest.model_validate(
        load_yaml(project_root / "examples/configs/dataset.yaml")
    )

    assert manifest.dataset_id == "xauusd_mt5_2025_2026"
    assert len(manifest.files) == 6


def test_dataset_manifest_rejects_duplicate_symbol_timeframe(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/dataset.yaml")
    payload["files"].append(dict(payload["files"][0]))

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(payload)


def test_dataset_manifest_rejects_path_escape(project_root: Path) -> None:
    payload = load_yaml(project_root / "examples/configs/dataset.yaml")
    payload["files"][0]["relative_path"] = "../outside.csv"

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(payload)
