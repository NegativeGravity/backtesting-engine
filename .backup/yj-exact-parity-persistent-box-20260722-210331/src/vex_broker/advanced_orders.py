from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from vex_contracts.enums import Side
from vex_contracts.orders import Order, OrderRequest

OCO_GROUP_TAG = "vex.oco.group"
OCO_AMBIGUOUS_POLICY_TAG = "vex.oco.ambiguous_policy"
OCO_POLICY_CANCEL_ALL = "cancel_all"
OCO_POLICY_FIRST_FILL = "first_fill"

STOP_AND_REVERSE_ENABLED_TAG = "vex.stop_and_reverse.enabled"
STOP_AND_REVERSE_STOP_TICKS_TAG = "vex.stop_and_reverse.stop_ticks"
STOP_AND_REVERSE_REWARD_RISK_TAG = "vex.stop_and_reverse.reward_risk"
STOP_AND_REVERSE_CHAIN_ID_TAG = "vex.stop_and_reverse.chain_id"
EXECUTION_RISK_REWARD_ENABLED_TAG = "vex.execution_risk_reward.enabled"
EXECUTION_REWARD_RISK_TAG = "vex.execution_risk_reward.ratio"
ENTRY_REQUIRE_FLAT_TAG = "vex.entry.require_flat"
ENTRY_REEVALUATE_AFTER_FLAT_TAG = "vex.entry.reevaluate_after_flat"
INTRABAR_ENTRY_TARGET_ALLOWED_TAG = "vex.intrabar_entry.target_allowed"


@dataclass(frozen=True, slots=True)
class ExecutionRiskRewardInstruction:
    reward_risk: Decimal


@dataclass(frozen=True, slots=True)
class StopAndReverseInstruction:
    reverse_stop_ticks: int
    reward_risk: Decimal
    chain_id: str | None


def oco_group(order: Order) -> str | None:
    value = order.request.tags.get(OCO_GROUP_TAG)
    return value if value else None


def oco_ambiguous_policy(order: Order) -> str:
    return order.request.tags.get(OCO_AMBIGUOUS_POLICY_TAG, OCO_POLICY_FIRST_FILL)


def tag_enabled(request: OrderRequest, key: str) -> bool:
    return request.tags.get(key, "false").lower() in {"true", "1", "yes"}


def entry_requires_flat(order: Order) -> bool:
    return tag_enabled(order.request, ENTRY_REQUIRE_FLAT_TAG)


def entry_reevaluate_after_flat(order: Order) -> bool:
    return tag_enabled(order.request, ENTRY_REEVALUATE_AFTER_FLAT_TAG)


def intrabar_entry_target_allowed(order: Order) -> bool:
    return tag_enabled(order.request, INTRABAR_ENTRY_TARGET_ALLOWED_TAG)


def execution_risk_reward_instruction(
    request: OrderRequest,
) -> ExecutionRiskRewardInstruction | None:
    if not tag_enabled(request, EXECUTION_RISK_REWARD_ENABLED_TAG):
        return None
    reward_raw = request.tags.get(EXECUTION_REWARD_RISK_TAG)
    if reward_raw is None:
        raise ValueError("execution risk/reward requires a reward_risk ratio")
    try:
        reward_risk = Decimal(reward_raw)
    except InvalidOperation as exc:
        raise ValueError("execution reward_risk must be a decimal") from exc
    if reward_risk <= 0:
        raise ValueError("execution reward_risk must be positive")
    if request.reduce_only:
        raise ValueError("execution risk/reward is not valid on reduce-only orders")
    if request.stop_loss_ticks is None:
        raise ValueError("execution risk/reward requires a stop loss")
    return ExecutionRiskRewardInstruction(reward_risk=reward_risk)


def stop_and_reverse_instruction(
    request: OrderRequest,
) -> StopAndReverseInstruction | None:
    if not tag_enabled(request, STOP_AND_REVERSE_ENABLED_TAG):
        return None
    stop_raw = request.tags.get(STOP_AND_REVERSE_STOP_TICKS_TAG)
    reward_raw = request.tags.get(STOP_AND_REVERSE_REWARD_RISK_TAG)
    if stop_raw is None or reward_raw is None:
        raise ValueError("stop-and-reverse tags require stop_ticks and reward_risk")
    try:
        reverse_stop_ticks = int(stop_raw)
    except ValueError as exc:
        raise ValueError("stop-and-reverse stop_ticks must be an integer") from exc
    try:
        reward_risk = Decimal(reward_raw)
    except InvalidOperation as exc:
        raise ValueError("stop-and-reverse reward_risk must be a decimal") from exc
    if reward_risk <= 0:
        raise ValueError("stop-and-reverse reward_risk must be positive")
    if request.reduce_only:
        raise ValueError("stop-and-reverse is not valid on reduce-only orders")
    if request.stop_loss_ticks is None:
        raise ValueError("stop-and-reverse requires an initial stop loss")
    if request.side is Side.BUY and reverse_stop_ticks <= request.stop_loss_ticks:
        raise ValueError("long stop-and-reverse stop must be above the initial stop")
    if request.side is Side.SELL and reverse_stop_ticks >= request.stop_loss_ticks:
        raise ValueError("short stop-and-reverse stop must be below the initial stop")
    chain_id = request.tags.get(STOP_AND_REVERSE_CHAIN_ID_TAG) or None
    return StopAndReverseInstruction(
        reverse_stop_ticks=reverse_stop_ticks,
        reward_risk=reward_risk,
        chain_id=chain_id,
    )


def validate_advanced_order_tags(request: OrderRequest) -> None:
    group = request.tags.get(OCO_GROUP_TAG)
    policy = request.tags.get(OCO_AMBIGUOUS_POLICY_TAG)
    if policy is not None and policy not in {
        OCO_POLICY_CANCEL_ALL,
        OCO_POLICY_FIRST_FILL,
    }:
        raise ValueError("unsupported OCO ambiguous policy")
    if policy is not None and not group:
        raise ValueError("OCO ambiguous policy requires an OCO group")
    execution_risk_reward_instruction(request)
    stop_and_reverse_instruction(request)
    for key in (
        ENTRY_REQUIRE_FLAT_TAG,
        ENTRY_REEVALUATE_AFTER_FLAT_TAG,
        INTRABAR_ENTRY_TARGET_ALLOWED_TAG,
    ):
        value = request.tags.get(key)
        if value is not None and value.lower() not in {
            "true",
            "false",
            "1",
            "0",
            "yes",
            "no",
        }:
            raise ValueError(f"{key} must be a boolean tag")
