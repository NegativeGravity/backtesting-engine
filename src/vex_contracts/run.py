from pydantic import AwareDatetime, Field, NonNegativeInt, PositiveInt, model_validator

from vex_contracts.account import AccountConfig
from vex_contracts.base import ContractModel
from vex_contracts.enums import RunStatus
from vex_contracts.execution import ExecutionConfig
from vex_contracts.identifiers import Identifier, SemanticVersion, Sha256Hex
from vex_contracts.risk import RiskConfig
from vex_contracts.strategy import StrategyInstanceConfig, StrategySubscription
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class DatasetReference(ContractModel):
    dataset_id: Identifier
    version: str = Field(min_length=1, max_length=64)
    content_hash: Sha256Hex | None = None


class SymbolProfileReference(ContractModel):
    profile_id: Identifier
    version: SemanticVersion


class ReplayRecordingConfig(ContractModel):
    enabled: bool = True
    snapshot_interval_events: PositiveInt = 5000
    persist_chart_commands: bool = True
    persist_account_snapshots: bool = True


class BacktestRunConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    run_id: Identifier
    name: str = Field(min_length=1, max_length=160)
    strategy: StrategyInstanceConfig
    dataset: DatasetReference
    symbol_profiles: tuple[SymbolProfileReference, ...] = Field(min_length=1)
    start_time: AwareDatetime
    end_time: AwareDatetime
    execution_timeframe: Timeframe
    subscriptions: tuple[StrategySubscription, ...] = Field(min_length=1)
    account: AccountConfig
    execution: ExecutionConfig
    risk: RiskConfig
    replay: ReplayRecordingConfig = Field(default_factory=ReplayRecordingConfig)
    random_seed: NonNegativeInt = 42
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_run(self) -> "BacktestRunConfig":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time")
        subscription_keys = [(item.symbol, item.timeframe) for item in self.subscriptions]
        if len(subscription_keys) != len(set(subscription_keys)):
            raise ValueError("subscriptions must be unique")
        if self.execution_timeframe not in {item.timeframe for item in self.subscriptions}:
            raise ValueError("execution_timeframe must be present in subscriptions")
        profile_keys = [(item.profile_id, item.version) for item in self.symbol_profiles]
        if len(profile_keys) != len(set(profile_keys)):
            raise ValueError("symbol_profiles must be unique")
        commission = self.execution.commission
        commission_currency = getattr(commission, "currency", None)
        if commission_currency is not None and commission_currency != self.account.currency:
            raise ValueError(
                "commission currency must match account currency in contract version 1"
            )
        return self


class RunProgress(ContractModel):
    run_id: Identifier
    status: RunStatus
    processed_events: NonNegativeInt = 0
    total_events: NonNegativeInt | None = None
    progress_percent: float = Field(default=0, ge=0, le=100)
    current_time_ns: NonNegativeInt | None = None
    message: str | None = Field(default=None, max_length=500)


class RunRecord(ContractModel):
    run_id: Identifier
    status: RunStatus
    config_fingerprint: Sha256Hex
    dataset_fingerprint: Sha256Hex
    strategy_fingerprint: Sha256Hex
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    failure_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "RunRecord":
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not precede created_at")
        if self.finished_at is not None:
            reference = self.started_at or self.created_at
            if self.finished_at < reference:
                raise ValueError("finished_at must not precede the run lifecycle")
        if self.status is RunStatus.FAILED and not self.failure_reason:
            raise ValueError("failed runs require failure_reason")
        if self.status is not RunStatus.FAILED and self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for failed runs")
        return self
