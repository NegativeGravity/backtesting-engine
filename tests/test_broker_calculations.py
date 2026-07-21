from decimal import Decimal
from pathlib import Path

from vex_broker.calculations import (
    commission_cost,
    required_margin,
    signed_price_pnl,
    spread_cost,
)
from vex_contracts.enums import PositionSide, Side
from vex_contracts.execution import (
    FixedPerOrderCommissionConfig,
    NoCommissionConfig,
    PercentageOfNotionalCommissionConfig,
    PerLotPerSideCommissionConfig,
    PerLotRoundTurnCommissionConfig,
)
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile


def profile(project_root: Path) -> SymbolProfile:
    return SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )


def test_pnl_and_spread_cost(project_root: Path) -> None:
    symbol = profile(project_root)

    pnl = signed_price_pnl(
        PositionSide.LONG,
        Decimal("260007"),
        Decimal("260100"),
        Decimal("0.5"),
        symbol,
    )
    cost = spread_cost(7, Decimal("0.5"), symbol)

    assert pnl == Decimal("46.5")
    assert cost == Decimal("1.75")


def test_commission_models(project_root: Path) -> None:
    symbol = profile(project_root)
    values = (
        commission_cost(NoCommissionConfig(), Side.BUY, Decimal("2"), 260000, symbol),
        commission_cost(
            FixedPerOrderCommissionConfig(amount=Decimal("4"), currency="USD"),
            Side.BUY,
            Decimal("2"),
            260000,
            symbol,
        ),
        commission_cost(
            PerLotPerSideCommissionConfig(amount_per_lot=Decimal("3.5"), currency="USD"),
            Side.BUY,
            Decimal("2"),
            260000,
            symbol,
        ),
        commission_cost(
            PerLotRoundTurnCommissionConfig(
                amount_per_lot=Decimal("7"),
                currency="USD",
            ),
            Side.BUY,
            Decimal("2"),
            260000,
            symbol,
        ),
        commission_cost(
            PercentageOfNotionalCommissionConfig(rate_bps=Decimal("1")),
            Side.BUY,
            Decimal("2"),
            260000,
            symbol,
        ),
    )

    assert values == (
        Decimal("0"),
        Decimal("4"),
        Decimal("7.0"),
        Decimal("7"),
        Decimal("52"),
    )


def test_cfd_margin(project_root: Path) -> None:
    symbol = profile(project_root)

    margin = required_margin(260000, Decimal("1"), symbol, Decimal("100"))

    assert margin == Decimal("2600")
