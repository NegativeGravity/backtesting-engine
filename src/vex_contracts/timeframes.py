from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"
    M6 = "M6"
    M10 = "M10"
    M12 = "M12"
    M15 = "M15"
    M20 = "M20"
    M30 = "M30"
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"
    H6 = "H6"
    H8 = "H8"
    H12 = "H12"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"

    @property
    def seconds(self) -> int | None:
        return _TIMEFRAME_SECONDS[self]


_TIMEFRAME_SECONDS: dict[Timeframe, int | None] = {
    Timeframe.M1: 60,
    Timeframe.M2: 120,
    Timeframe.M3: 180,
    Timeframe.M4: 240,
    Timeframe.M5: 300,
    Timeframe.M6: 360,
    Timeframe.M10: 600,
    Timeframe.M12: 720,
    Timeframe.M15: 900,
    Timeframe.M20: 1200,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H2: 7200,
    Timeframe.H3: 10800,
    Timeframe.H4: 14400,
    Timeframe.H6: 21600,
    Timeframe.H8: 28800,
    Timeframe.H12: 43200,
    Timeframe.D1: 86400,
    Timeframe.W1: 604800,
    Timeframe.MN1: None,
}
