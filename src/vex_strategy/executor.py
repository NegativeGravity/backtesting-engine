from vex_broker.models import BrokerResult
from vex_broker.simulator import BrokerSimulator
from vex_contracts.orders import (
    OrderCancellationRequest,
    OrderModificationRequest,
    OrderRequest,
)
from vex_contracts.strategy_runtime import (
    CancelOrderAction,
    ModifyOrderAction,
    StrategyAction,
    SubmitOrderAction,
)


class StrategyActionExecutor:
    def __init__(self, broker: BrokerSimulator) -> None:
        self._broker = broker

    def execute(self, action: StrategyAction) -> BrokerResult:
        if isinstance(action, SubmitOrderAction):
            return self._submit(action)
        if isinstance(action, CancelOrderAction):
            return self._broker.cancel_order(
                OrderCancellationRequest(
                    order_id=action.order_id,
                    requested_time_ns=action.requested_time_ns,
                    reason=action.reason,
                )
            )
        if isinstance(action, ModifyOrderAction):
            return self._broker.modify_order(
                OrderModificationRequest(
                    order_id=action.order_id,
                    requested_time_ns=action.requested_time_ns,
                    price_ticks=action.price_ticks,
                    stop_loss_ticks=action.stop_loss_ticks,
                    take_profit_ticks=action.take_profit_ticks,
                    expiration_time_ns=action.expiration_time_ns,
                )
            )
        return self._broker.modify_position_protection(
            position_id=action.position_id,
            requested_time_ns=action.requested_time_ns,
            stop_loss_ticks=action.stop_loss_ticks,
            take_profit_ticks=action.take_profit_ticks,
        )

    def _submit(self, action: SubmitOrderAction) -> BrokerResult:
        intent = action.intent
        volume = intent.volume_lots
        if volume is None:
            if intent.sizing_price_ticks is None:
                raise ValueError("risk-sized order is missing sizing_price_ticks")
            volume = self._broker.size_position(
                intent.symbol,
                intent.sizing_price_ticks,
                intent.stop_loss_ticks,
            )
        return self._broker.submit_order(
            OrderRequest(
                client_order_id=intent.client_order_id,
                run_id=self._broker.run_config.run_id,
                strategy_instance_id=self._broker.run_config.strategy.instance_id,
                symbol=intent.symbol,
                side=intent.side,
                order_type=intent.order_type,
                volume_lots=volume,
                created_time_ns=action.requested_time_ns,
                price_ticks=intent.price_ticks,
                stop_loss_ticks=intent.stop_loss_ticks,
                take_profit_ticks=intent.take_profit_ticks,
                time_in_force=intent.time_in_force,
                expiration_time_ns=intent.expiration_time_ns,
                reduce_only=intent.reduce_only,
                position_id=intent.position_id,
                tags=intent.tags,
            )
        )
