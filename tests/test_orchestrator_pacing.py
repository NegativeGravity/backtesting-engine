import pytest

from vex_orchestrator.pacing import DeadlinePacer, ui_publish_interval


def test_deadline_pacer_accounts_for_processing_time() -> None:
    pacer = DeadlinePacer()

    assert pacer.delay(100, now=10.0) == pytest.approx(0.01)
    assert pacer.delay(100, now=10.006) == pytest.approx(0.014)
    assert pacer.delay(100, now=10.022) == pytest.approx(0.008)


def test_deadline_pacer_resets_after_large_drift() -> None:
    pacer = DeadlinePacer(maximum_drift_seconds=0.1)
    pacer.delay(10, now=1.0)

    assert pacer.delay(10, now=2.0) == pytest.approx(0.1)


def test_ui_publish_interval_decreases_render_pressure_at_high_speed() -> None:
    assert ui_publish_interval(100) == pytest.approx(1 / 30)
    assert ui_publish_interval(1_000) == pytest.approx(1 / 20)
    assert ui_publish_interval(10_000) == pytest.approx(1 / 12)
    assert ui_publish_interval(100_000) == pytest.approx(1 / 8)


def test_ui_publish_interval_rejects_invalid_rate() -> None:
    with pytest.raises(ValueError):
        ui_publish_interval(0)
