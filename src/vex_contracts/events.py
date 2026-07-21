from datetime import UTC, datetime

from pydantic import AwareDatetime, Field, NonNegativeInt

from vex_contracts.base import ContractModel
from vex_contracts.enums import EventType
from vex_contracts.identifiers import Identifier, SymbolCode, new_identifier
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class EventEnvelope[PayloadT](ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    event_id: Identifier = Field(default_factory=lambda: new_identifier("evt"))
    run_id: Identifier
    sequence: NonNegativeInt
    event_type: EventType
    event_time_ns: NonNegativeInt
    emitted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy_instance_id: Identifier | None = None
    symbol: SymbolCode | None = None
    correlation_id: Identifier | None = None
    causation_id: Identifier | None = None
    payload: PayloadT


def create_event[PayloadT](
    *,
    run_id: str,
    sequence: int,
    event_type: EventType,
    event_time_ns: int,
    payload: PayloadT,
    strategy_instance_id: str | None = None,
    symbol: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> EventEnvelope[PayloadT]:
    return EventEnvelope[PayloadT](
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        event_time_ns=event_time_ns,
        payload=payload,
        strategy_instance_id=strategy_instance_id,
        symbol=symbol,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
