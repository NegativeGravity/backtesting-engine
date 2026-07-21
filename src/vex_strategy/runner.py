from pathlib import Path

from vex_contracts.enums import PriceBasis
from vex_contracts.run import BacktestRunConfig
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyBacktestReport, StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_data_engine.catalog import ParquetBarStore
from vex_strategy.observer import StrategyRunObserver
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.session import StrategyBacktestSession, bar_from_row, datetime_to_ns


class StrategyBacktestRunner:
    def __init__(
        self,
        run_config: BacktestRunConfig,
        descriptor: StrategyDescriptor,
        runtime_config: StrategyRuntimeConfig,
        symbol_profiles: dict[str, SymbolProfile],
        store: ParquetBarStore,
        output_recorder: StrategyOutputRecorder | None = None,
        price_basis: PriceBasis = PriceBasis.BID,
        observer: StrategyRunObserver | None = None,
        strategy_import_paths: tuple[str | Path, ...] = (),
    ) -> None:
        self.session = StrategyBacktestSession(
            run_config,
            descriptor,
            runtime_config,
            symbol_profiles,
            store,
            output_recorder,
            price_basis,
            observer,
            strategy_import_paths,
        )
        self.run_config = self.session.run_config
        self.descriptor = self.session.descriptor
        self.runtime_config = self.session.runtime_config
        self.symbol_profiles = self.session.symbol_profiles
        self.store = self.session.store
        self.recorder = self.session.recorder
        self.broker = self.session.broker
        self.observer = self.session.observer

    def run(self, max_close_batches: int | None = None) -> StrategyBacktestReport:
        self.session.start()
        while not self.session.finished:
            if (
                max_close_batches is not None
                and self.session.counters.processed_close_batches >= max_close_batches
            ):
                return self.session.finish("max_close_batches_reached").report or self._report()
            result = self.session.step()
            if result.completed:
                return result.report or self._report()
        return self._report()

    def _report(self) -> StrategyBacktestReport:
        report = self.session.report
        if report is None:
            raise RuntimeError("strategy session completed without a report")
        return report


__all__ = ["StrategyBacktestRunner", "bar_from_row", "datetime_to_ns"]
