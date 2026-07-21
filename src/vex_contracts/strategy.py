from pydantic import Field, field_validator, model_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import HigherTimeframeAccess
from vex_contracts.identifiers import Identifier, SemanticVersion, SymbolCode
from vex_contracts.json_types import JsonValue
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class StrategySubscription(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    higher_timeframe_access: HigherTimeframeAccess = HigherTimeframeAccess.CLOSED_ONLY


class StrategyCapabilities(ContractModel):
    chart_drawings: bool = True
    custom_series: bool = True
    bar_events: bool = True
    quote_events: bool = False
    order_updates: bool = True


class StrategyDescriptor(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    strategy_id: Identifier
    name: str = Field(min_length=1, max_length=160)
    version: SemanticVersion
    entrypoint: str = Field(min_length=3, max_length=256)
    description: str = Field(default="", max_length=2000)
    subscriptions: tuple[StrategySubscription, ...] = Field(min_length=1)
    capabilities: StrategyCapabilities = Field(default_factory=StrategyCapabilities)
    default_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        module, separator, target = value.partition(":")
        if not separator or not module or not target:
            raise ValueError("entrypoint must use the module:object format")
        return value

    @model_validator(mode="after")
    def validate_subscriptions(self) -> "StrategyDescriptor":
        keys = [(item.symbol, item.timeframe) for item in self.subscriptions]
        if len(keys) != len(set(keys)):
            raise ValueError("subscriptions must be unique")
        return self


class StrategyInstanceConfig(ContractModel):
    strategy_id: Identifier
    version: SemanticVersion
    instance_id: Identifier
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
