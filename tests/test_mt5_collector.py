from collections import namedtuple
from types import ModuleType

from vex_contracts.enums import PositionMode
from vex_contracts.mt5_bridge import Mt5BridgeConfig
from vex_mt5.collector import collect_snapshot


class FakeMt5(ModuleType):
    def __init__(self) -> None:
        super().__init__("MetaTrader5")
        self.shutdown_called = False

    def initialize(self, **kwargs: object) -> bool:
        return kwargs["timeout"] == 60000

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def terminal_info(self) -> object:
        model = namedtuple(
            "TerminalInfo",
            [
                "name",
                "company",
                "build",
                "connected",
                "trade_allowed",
                "tradeapi_disabled",
                "path",
                "data_path",
                "commondata_path",
                "maxbars",
                "ping_last",
            ],
        )
        return model(
            "MetaTrader 5",
            "Test",
            5000,
            True,
            True,
            False,
            "C:/MT5",
            "C:/MT5/Data",
            "C:/MT5/Common",
            100000,
            1000,
        )

    def account_info(self) -> object:
        model = namedtuple(
            "AccountInfo",
            [
                "login",
                "server",
                "company",
                "name",
                "currency",
                "leverage",
                "margin_mode",
                "trade_allowed",
                "trade_expert",
                "balance",
                "credit",
                "profit",
                "equity",
                "margin",
                "margin_free",
                "margin_level",
                "margin_so_mode",
                "margin_so_call",
                "margin_so_so",
            ],
        )
        return model(
            1,
            "Demo",
            "Test",
            "User",
            "USD",
            100,
            2,
            True,
            True,
            100000,
            0,
            0,
            100000,
            0,
            100000,
            0,
            0,
            100,
            50,
        )

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        return symbol == "XAUUSD" and enabled

    def symbol_info(self, symbol: str) -> object:
        model = namedtuple(
            "SymbolInfo",
            [
                "path",
                "description",
                "currency_base",
                "currency_profit",
                "currency_margin",
                "digits",
                "point",
                "spread",
                "spread_float",
                "trade_calc_mode",
                "trade_mode",
                "trade_exemode",
                "order_mode",
                "filling_mode",
                "expiration_mode",
                "trade_stops_level",
                "trade_freeze_level",
                "trade_tick_size",
                "trade_tick_value",
                "trade_tick_value_profit",
                "trade_tick_value_loss",
                "trade_contract_size",
                "volume_min",
                "volume_max",
                "volume_step",
                "volume_limit",
                "margin_initial",
                "margin_maintenance",
                "margin_hedged",
                "margin_hedged_use_leg",
                "swap_mode",
                "swap_long",
                "swap_short",
            ],
        )
        return model(
            symbol,
            symbol,
            "XAU",
            "USD",
            "USD",
            2,
            0.01,
            7,
            False,
            3,
            4,
            2,
            127,
            3,
            15,
            0,
            0,
            0.01,
            1,
            1,
            1,
            100,
            0.01,
            100,
            0.01,
            0,
            0,
            0,
            0,
            False,
            1,
            -35,
            12,
        )

    def symbol_info_tick(self, symbol: str) -> object:
        model = namedtuple("TickInfo", "bid ask last time_msc")
        return model(2650, 2650.07, 0, 1)

    def order_calc_profit(
        self,
        order_type: int,
        symbol: str,
        volume: float,
        open_price: float,
        close_price: float,
    ) -> float:
        del order_type, symbol
        return abs(close_price - open_price) * 100 * volume

    def order_calc_margin(
        self,
        order_type: int,
        symbol: str,
        volume: float,
        open_price: float,
    ) -> float:
        del order_type, symbol
        return open_price * 100 * volume / 100


def test_collector_builds_snapshot_and_always_shuts_down() -> None:
    module = FakeMt5()
    snapshot = collect_snapshot(
        Mt5BridgeConfig(symbols=("XAUUSD",), sample_volumes=("0.10",)),
        module,
    )
    assert module.shutdown_called
    assert snapshot.account.position_mode is PositionMode.HEDGING
    assert snapshot.symbols[0].symbol == "XAUUSD"
    assert len(snapshot.calculation_samples) == 2
