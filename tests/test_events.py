from vex_contracts.enums import EventType
from vex_contracts.events import EventEnvelope, create_event


def test_event_envelope_preserves_run_ordering_fields() -> None:
    event = create_event(
        run_id="run_example_0001",
        sequence=12,
        event_type=EventType.BAR_CLOSED,
        event_time_ns=1_000_000_000,
        payload={"timeframe": "M1"},
        symbol="XAUUSD",
    )

    assert isinstance(event, EventEnvelope)
    assert event.sequence == 12
    assert event.event_type is EventType.BAR_CLOSED
    assert event.symbol == "XAUUSD"
    assert event.event_id.startswith("evt_")
