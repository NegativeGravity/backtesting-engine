from datetime import UTC, datetime

from pydantic import JsonValue

from vex_broker.ids import DeterministicIdGenerator
from vex_contracts.enums import EventType
from vex_contracts.events import EventEnvelope


class BrokerEventFactory:
    def __init__(self, run_id: str, ids: DeterministicIdGenerator) -> None:
        self._run_id = run_id
        self._ids = ids
        self._sequence = 0

    @property
    def sequence(self) -> int:
        return self._sequence

    def create(
        self,
        event_type: EventType,
        event_time_ns: int,
        payload: dict[str, JsonValue],
        strategy_instance_id: str | None = None,
        symbol: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> EventEnvelope[dict[str, JsonValue]]:
        self._sequence += 1
        return EventEnvelope[dict[str, JsonValue]](
            event_id=self._ids.next("evt"),
            run_id=self._run_id,
            sequence=self._sequence,
            event_type=event_type,
            event_time_ns=event_time_ns,
            emitted_at=datetime.fromtimestamp(event_time_ns / 1_000_000_000, tz=UTC),
            strategy_instance_id=strategy_instance_id,
            symbol=symbol,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )
