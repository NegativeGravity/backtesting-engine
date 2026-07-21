from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from vex_contracts.chart import ChartCommand
from vex_contracts.serialization import load_yaml


def test_chart_command_validates_dynamic_trend_line(project_root: Path) -> None:
    command = TypeAdapter(ChartCommand).validate_python(
        load_yaml(project_root / "examples/configs/chart_command.yaml")
    )

    assert command.command_type.value == "upsert_drawing"
    assert command.drawing.revision == 1


def test_long_risk_reward_rejects_inverted_levels() -> None:
    payload = {
        "command_type": "upsert_drawing",
        "drawing": {
            "kind": "risk_reward",
            "drawing_id": "risk_reward_0001",
            "layer_id": "strategy_layer",
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "trade_id": "trade_0001",
            "side": "long",
            "entry_time_ns": 1,
            "entry_price_ticks": "100",
            "stop_price_ticks": "110",
            "target_price_ticks": "90",
            "risk_fill": {"color": "#FF0000", "opacity": "0.2"},
            "reward_fill": {"color": "#00FF00", "opacity": "0.2"},
            "entry_line": {"color": "#FFFFFF"},
            "stop_line": {"color": "#FF0000"},
            "target_line": {"color": "#00FF00"},
        },
    }

    with pytest.raises(ValidationError):
        TypeAdapter(ChartCommand).validate_python(payload)
