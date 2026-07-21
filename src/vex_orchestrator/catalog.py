import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_json, load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_orchestrator.models import StrategyPackageManifest, StrategyPackageSummary


class StrategyPackageNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class StrategyPackage:
    root: Path
    manifest: StrategyPackageManifest
    descriptor: StrategyDescriptor
    run_config: BacktestRunConfig
    runtime_config: StrategyRuntimeConfig
    symbol_profiles: tuple[SymbolProfile, ...]
    import_report_path: Path

    @property
    def summary(self) -> StrategyPackageSummary:
        return StrategyPackageSummary(
            package_id=self.manifest.package_id,
            strategy_id=self.descriptor.strategy_id,
            name=self.descriptor.name,
            version=self.descriptor.version,
            description=self.descriptor.description,
            entrypoint=self.descriptor.entrypoint,
            package_path=self.root.name,
            tags=self.descriptor.tags,
            enabled=self.manifest.enabled,
        )


class StrategyPackageCatalog:
    def __init__(
        self,
        project_root: str | Path,
        strategies_root: str | Path = "strategies",
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.strategies_root = (self.project_root / strategies_root).resolve()
        self._packages: dict[str, StrategyPackage] = {}
        self._install_import_path()
        self.refresh()

    def refresh(self) -> None:
        packages: dict[str, StrategyPackage] = {}
        if not self.strategies_root.exists():
            self._packages = packages
            return
        for manifest_path in sorted(self.strategies_root.glob("*/package.yaml")):
            manifest = self._load_model(manifest_path, StrategyPackageManifest)
            if not manifest.enabled:
                continue
            package = self._load_package(manifest_path, manifest)
            if package.manifest.package_id in packages:
                raise ValueError(f"duplicate strategy package: {package.manifest.package_id}")
            packages[package.manifest.package_id] = package
        self._packages = packages

    def summaries(self) -> tuple[StrategyPackageSummary, ...]:
        return tuple(
            package.summary
            for package in sorted(
                self._packages.values(), key=lambda item: item.manifest.package_id
            )
            if package.manifest.enabled
        )

    def get(self, package_id: str) -> StrategyPackage:
        package = self._packages.get(package_id)
        if package is None or not package.manifest.enabled:
            raise StrategyPackageNotFoundError(package_id)
        return package

    def _load_package(
        self,
        manifest_path: Path,
        manifest: StrategyPackageManifest | None = None,
    ) -> StrategyPackage:
        root = manifest_path.parent.resolve()
        resolved_manifest = manifest or self._load_model(manifest_path, StrategyPackageManifest)
        descriptor_path = self._resolve(root, resolved_manifest.descriptor_path)
        run_path = self._resolve(root, resolved_manifest.run_config_path)
        runtime_path = self._resolve(root, resolved_manifest.runtime_config_path)
        profiles = tuple(
            self._load_model(self._resolve(root, path), SymbolProfile)
            for path in resolved_manifest.symbol_profile_paths
        )
        import_report_path = self._resolve(root, resolved_manifest.import_report_path)
        if not import_report_path.exists():
            raise FileNotFoundError(import_report_path)
        descriptor = self._load_model(descriptor_path, StrategyDescriptor)
        run_config = self._load_model(run_path, BacktestRunConfig)
        runtime_config = self._load_model(runtime_path, StrategyRuntimeConfig)
        if run_config.strategy.strategy_id != descriptor.strategy_id:
            raise ValueError(
                "strategy package "
                f"{resolved_manifest.package_id} has mismatched run and descriptor IDs"
            )
        if run_config.strategy.version != descriptor.version:
            raise ValueError(
                "strategy package "
                f"{resolved_manifest.package_id} has mismatched run and descriptor versions"
            )
        return StrategyPackage(
            root=root,
            manifest=resolved_manifest,
            descriptor=descriptor,
            run_config=run_config,
            runtime_config=runtime_config,
            symbol_profiles=profiles,
            import_report_path=import_report_path,
        )

    def _install_import_path(self) -> None:
        path = str(self.strategies_root)
        if path not in sys.path:
            sys.path.insert(0, path)
        existing = os.environ.get("PYTHONPATH", "")
        parts = [part for part in existing.split(os.pathsep) if part]
        if path not in parts:
            os.environ["PYTHONPATH"] = os.pathsep.join([path, *parts])

    def _resolve(self, root: Path, value: str) -> Path:
        path = (root / value).resolve()
        if not path.is_relative_to(self.project_root):
            raise ValueError(f"strategy package path escapes project root: {value}")
        return path

    @staticmethod
    def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
        value: Any = load_json(path) if path.suffix.lower() == ".json" else load_yaml(path)
        return model.model_validate(value)
