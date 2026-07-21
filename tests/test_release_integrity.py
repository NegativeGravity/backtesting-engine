import json
import tomllib
from pathlib import Path

import yaml

from vex_contracts.version import PACKAGE_VERSION


def test_release_versions_are_aligned() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads(Path("apps/dashboard_web/package.json").read_text(encoding="utf-8"))
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert version == PACKAGE_VERSION
    assert frontend["version"] == version
    assert compose["services"]["bootstrap"]["image"] == f"vex-backtesting-engine:{version}"
    assert compose["services"]["engine"]["image"] == f"vex-backtesting-engine:{version}"
    assert compose["services"]["dashboard"]["image"] == f"vex-backtesting-engine:{version}"


def test_release_has_websocket_runtime_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = tuple(pyproject["project"]["dependencies"])
    assert any(dependency.startswith("websockets") for dependency in dependencies)


def test_lock_files_only_reference_public_registries() -> None:
    uv_lock = Path("uv.lock").read_text(encoding="utf-8")
    npm_lock = Path("apps/dashboard_web/package-lock.json").read_text(encoding="utf-8")
    combined = f"{uv_lock}\n{npm_lock}".lower()
    assert "applied-caas" not in combined
    assert "runflare" not in combined
    assert "packages.openai.org" not in combined
    assert "files.pythonhosted.org" in uv_lock
    assert "registry.npmjs.org" in npm_lock
