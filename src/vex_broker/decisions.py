from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FillDecision:
    price_ticks: int
    reference_price_ticks: int
    slippage_ticks: int
    reason: str
    at_open: bool


@dataclass(frozen=True, slots=True)
class ProtectionDecision:
    price_ticks: int
    reference_price_ticks: int
    slippage_ticks: int
    reason: str
    ambiguous: bool
