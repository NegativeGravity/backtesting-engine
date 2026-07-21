from collections.abc import Iterable
from decimal import Decimal
from typing import cast

from pydantic import BaseModel, JsonValue

from vex_broker.calculations import (
    commission_cost,
    money_for_ticks,
    points_to_ticks,
    required_margin,
    signed_price_pnl,
    slippage_cost,
    spread_cost,
)
from vex_broker.decisions import FillDecision, ProtectionDecision
from vex_broker.events import BrokerEventFactory
from vex_broker.exceptions import (
    AmbiguousBarError,
    BrokerConfigurationError,
    OrderNotFoundError,
    OrderRejectedError,
    PositionNotFoundError,
)
from vex_broker.ids import DeterministicIdGenerator
from vex_broker.models import AccountState, BrokerResult, BrokerState, PositionState
from vex_broker.pricing import PriceResolver, ResolvedBar
from vex_broker.sizing import PositionSizer
from vex_contracts.broker import BrokerSimulationReport, BrokerStateSnapshot
from vex_contracts.enums import (
    EventType,
    IntrabarPolicy,
    OrderStatus,
    OrderType,
    PositionMode,
    PositionSide,
    PositionStatus,
    PriceBasis,
    Side,
)
from vex_contracts.events import EventEnvelope
from vex_contracts.market import Bar
from vex_contracts.order_state_machine import apply_fill, transition_order
from vex_contracts.orders import (
    Fill,
    Order,
    OrderCancellationRequest,
    OrderModificationRequest,
    OrderRequest,
)
from vex_contracts.positions import AccountSnapshot, Position, Trade
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import fingerprint
from vex_contracts.symbol import SymbolProfile

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class BrokerSimulator:
    def __init__(
        self,
        run_config: BacktestRunConfig,
        symbol_profiles: dict[str, SymbolProfile],
        price_basis: PriceBasis = PriceBasis.BID,
    ) -> None:
        self.run_config = run_config
        self.symbol_profiles = dict(symbol_profiles)
        self._validate_configuration()
        self._ids = DeterministicIdGenerator(run_config.run_id)
        self._events = BrokerEventFactory(run_config.run_id, self._ids)
        initial = run_config.account.initial_balance
        account = AccountState(
            balance=initial,
            equity=initial,
            free_margin=initial,
            peak_equity=initial,
        )
        self.state = BrokerState(account=account)
        self._price_basis = price_basis
        self._resolvers = {
            symbol: PriceResolver(
                profile,
                price_basis,
                run_config.execution.spread,
            )
            for symbol, profile in self.symbol_profiles.items()
        }
        self._client_order_ids: set[str] = set()
        self._last_resolved: dict[str, ResolvedBar] = {}

    @property
    def open_positions(self) -> tuple[Position, ...]:
        return tuple(
            self._position_contract(item)
            for item in sorted(self.state.positions.values(), key=lambda value: value.position_id)
        )

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(self.state.orders[key] for key in sorted(self.state.orders))

    @property
    def trades(self) -> tuple[Trade, ...]:
        return tuple(self.state.trades)

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self.state.fills)

    @property
    def account_snapshot(self) -> AccountSnapshot:
        return self._snapshot(self.state.current_time_ns)

    @property
    def state_snapshot(self) -> BrokerStateSnapshot:
        return BrokerStateSnapshot(
            run_id=self.run_config.run_id,
            timestamp_ns=self.state.current_time_ns,
            event_sequence=self._events.sequence,
            account=self.account_snapshot,
            orders=self.orders,
            positions=self.open_positions,
        )

    def build_report(self, processed_bars: int) -> BrokerSimulationReport:
        commission = sum((fill.commission for fill in self.state.fills), start=ZERO)
        spread = sum((fill.spread_cost for fill in self.state.fills), start=ZERO)
        slippage = sum((fill.slippage_cost for fill in self.state.fills), start=ZERO)
        realized_swap = sum((trade.swap for trade in self.state.trades), start=ZERO)
        open_swap = sum((position.swap for position in self.state.positions.values()), start=ZERO)
        swap = realized_swap + open_swap
        net_pnl = self.state.account.equity - self.run_config.account.initial_balance
        gross_pnl = net_pnl + commission + spread + slippage - swap
        digest = fingerprint(
            {
                "run_id": self.run_config.run_id,
                "events": self.state.events,
                "orders": self.orders,
                "fills": self.fills,
                "trades": self.trades,
                "account": self.account_snapshot,
            }
        )
        rejected = sum(order.status is OrderStatus.REJECTED for order in self.orders)
        cancelled = sum(order.status is OrderStatus.CANCELLED for order in self.orders)
        return BrokerSimulationReport(
            report_id=f"broker_report_{digest[:24]}",
            run_id=self.run_config.run_id,
            processed_bars=processed_bars,
            event_count=self._events.sequence,
            order_count=len(self.orders),
            fill_count=len(self.fills),
            trade_count=len(self.trades),
            open_position_count=len(self.open_positions),
            rejected_order_count=rejected,
            cancelled_order_count=cancelled,
            final_account=self.account_snapshot,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            commission=commission,
            spread_cost=spread,
            slippage_cost=slippage,
            swap=swap,
            deterministic_digest=digest,
        )

    def size_position(
        self,
        symbol: str,
        entry_price_ticks: int,
        stop_loss_ticks: int | None,
        requested_volume_lots: Decimal | None = None,
    ) -> Decimal:
        return PositionSizer.size(
            self.run_config.risk.default_sizing,
            self.state.account.equity,
            entry_price_ticks,
            stop_loss_ticks,
            self._require_profile(symbol),
            requested_volume_lots,
        )

    def submit_order(self, request: OrderRequest) -> BrokerResult:
        events: list[EventEnvelope[dict[str, JsonValue]]] = []
        order = Order(order_id=self._ids.next("ord"), request=request)
        self.state.orders[order.order_id] = order
        events.append(self._emit(EventType.ORDER_CREATED, request.created_time_ns, order))
        reason = self._submission_rejection_reason(request)
        if reason is not None:
            rejected = transition_order(
                order,
                OrderStatus.REJECTED,
                request.created_time_ns,
                rejection_reason=reason,
            )
            self.state.orders[order.order_id] = rejected
            events.append(self._emit(EventType.ORDER_REJECTED, request.created_time_ns, rejected))
            return self._result(events=events)
        accepted = transition_order(order, OrderStatus.ACCEPTED, request.created_time_ns)
        self.state.orders[order.order_id] = accepted
        self._client_order_ids.add(request.client_order_id)
        events.append(self._emit(EventType.ORDER_ACCEPTED, request.created_time_ns, accepted))
        return self._result(events=events)

    def cancel_order(self, request: OrderCancellationRequest) -> BrokerResult:
        order = self._require_order(request.order_id)
        if order.status not in {OrderStatus.ACCEPTED, OrderStatus.ACTIVE}:
            raise OrderRejectedError(f"order {order.order_id} cannot be cancelled")
        if "broker_protection" in order.request.tags or "broker_exit" in order.request.tags:
            raise OrderRejectedError("broker-owned orders cannot be cancelled directly")
        cancelled = transition_order(order, OrderStatus.CANCELLED, request.requested_time_ns)
        self.state.orders[order.order_id] = cancelled
        event = self._emit(
            EventType.ORDER_CANCELLED,
            request.requested_time_ns,
            cancelled,
            extra={"reason": request.reason},
        )
        return self._result(events=[event])

    def modify_order(self, request: OrderModificationRequest) -> BrokerResult:
        order = self._require_order(request.order_id)
        if order.status not in {OrderStatus.ACCEPTED, OrderStatus.ACTIVE}:
            raise OrderRejectedError(f"order {order.order_id} cannot be modified")
        if "broker_protection" in order.request.tags or "broker_exit" in order.request.tags:
            raise OrderRejectedError("broker-owned orders cannot be modified directly")
        if request.requested_time_ns < order.request.created_time_ns:
            raise OrderRejectedError("modification time precedes order creation")
        updates: dict[str, object] = {}
        if request.price_ticks is not None:
            if order.request.order_type is OrderType.MARKET:
                raise OrderRejectedError("market order price cannot be modified")
            updates["price_ticks"] = request.price_ticks
        if request.stop_loss_ticks is not None:
            updates["stop_loss_ticks"] = request.stop_loss_ticks
        if request.take_profit_ticks is not None:
            updates["take_profit_ticks"] = request.take_profit_ticks
        if request.expiration_time_ns is not None:
            if request.expiration_time_ns <= request.requested_time_ns:
                raise OrderRejectedError("expiration must be later than modification time")
            updates["expiration_time_ns"] = request.expiration_time_ns
        if not updates:
            raise OrderRejectedError("order modification contains no changes")
        modified_request = order.request.model_copy(update=updates)
        modified_request = OrderRequest.model_validate(modified_request.model_dump())
        self._validate_pending_protection(modified_request)
        modified = order.model_copy(
            update={
                "request": modified_request,
                "revision": order.revision + 1,
            }
        )
        self.state.orders[order.order_id] = modified
        event = self._emit(EventType.ORDER_MODIFIED, request.requested_time_ns, modified)
        return self._result(events=[event])

    def modify_position_protection(
        self,
        position_id: str,
        requested_time_ns: int,
        stop_loss_ticks: int | None,
        take_profit_ticks: int | None,
    ) -> BrokerResult:
        position = self._require_position(position_id)
        self._validate_position_protection(
            position.side,
            int(position.average_entry_price_ticks),
            stop_loss_ticks,
            take_profit_ticks,
            self.symbol_profiles[position.symbol],
        )
        events: list[EventEnvelope[dict[str, JsonValue]]] = []
        position.stop_loss_ticks = stop_loss_ticks
        position.take_profit_ticks = take_profit_ticks
        position.last_update_time_ns = requested_time_ns
        self._sync_protection_orders(position, requested_time_ns, events)
        contract = self._position_contract(position)
        events.append(self._emit(EventType.POSITION_UPDATED, requested_time_ns, contract))
        return self._result(events=events)

    def process_bar(self, bar: Bar) -> BrokerResult:
        self._validate_bar_sequence(bar)
        self._require_profile(bar.symbol)
        resolver = self._resolvers[bar.symbol]
        resolved = resolver.resolve(bar)
        self._last_resolved[bar.symbol] = resolved
        events: list[EventEnvelope[dict[str, JsonValue]]] = []
        fills: list[Fill] = []
        trades: list[Trade] = []
        preexisting = set(self.state.positions)
        intrabar_entries: set[str] = set()
        self.state.current_time_ns = bar.open_time_ns
        self._expire_orders(bar, events)
        self._activate_orders(bar, events)
        for order in self._active_orders(bar.symbol):
            decision = self._order_fill_decision(order, resolved)
            if decision is None:
                continue
            fill_time_ns = bar.open_time_ns if decision.at_open else bar.close_time_ns
            opened = self._execute_order(
                order,
                decision,
                resolved.spread_ticks,
                fill_time_ns,
                fills,
                trades,
                events,
            )
            if not decision.at_open:
                intrabar_entries.update(opened)
        self._process_protections(
            bar,
            resolved,
            preexisting,
            intrabar_entries,
            fills,
            trades,
            events,
        )
        self._update_positions_for_bar(bar, resolved)
        self._revalue_account(bar.close_time_ns, resolved)
        self._process_margin_state(bar, resolved, fills, trades, events)
        self._apply_negative_balance_protection(bar.close_time_ns, resolved)
        snapshot = self._snapshot(bar.close_time_ns, self._events.sequence + 1)
        events.append(self._emit(EventType.ACCOUNT_UPDATED, bar.close_time_ns, snapshot))
        self.state.last_bar_sequence[bar.symbol] = bar.sequence
        self.state.last_bar_close_time_ns[bar.symbol] = bar.close_time_ns
        self.state.current_time_ns = bar.close_time_ns
        return self._result(
            events=events,
            fills=fills,
            trades=trades,
            snapshot=snapshot,
        )

    def _validate_configuration(self) -> None:
        referenced = {item.profile_id for item in self.run_config.symbol_profiles}
        provided = {profile.profile_id for profile in self.symbol_profiles.values()}
        if referenced != provided:
            raise BrokerConfigurationError("symbol profile references do not match profiles")
        subscription_symbols = {item.symbol for item in self.run_config.subscriptions}
        if subscription_symbols != set(self.symbol_profiles):
            raise BrokerConfigurationError("each subscribed symbol requires one symbol profile")
        for profile in self.symbol_profiles.values():
            if profile.currency_profit != self.run_config.account.currency:
                raise BrokerConfigurationError(
                    "phase 2 requires profit currency to match account currency"
                )
            if profile.currency_margin != self.run_config.account.currency:
                raise BrokerConfigurationError(
                    "phase 2 requires margin currency to match account currency"
                )

    def _submission_rejection_reason(self, request: OrderRequest) -> str | None:
        if request.run_id != self.run_config.run_id:
            return "run_id_mismatch"
        if request.created_time_ns < self.state.current_time_ns:
            return "stale_order_time"
        if request.strategy_instance_id != self.run_config.strategy.instance_id:
            return "strategy_instance_id_mismatch"
        if request.symbol not in self.symbol_profiles:
            return "unknown_symbol"
        if request.client_order_id in self._client_order_ids:
            return "duplicate_client_order_id"
        profile = self.symbol_profiles[request.symbol]
        try:
            if profile.normalize_volume(request.volume_lots) != request.volume_lots:
                return "volume_not_aligned"
            self._validate_pending_protection(request)
        except ValueError as exc:
            return str(exc).replace(" ", "_")
        if request.reduce_only:
            position = self.state.positions.get(cast(str, request.position_id))
            if position is None:
                return "reduce_only_position_not_found"
            if position.symbol != request.symbol:
                return "reduce_only_symbol_mismatch"
            expected_side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
            if request.side is not expected_side:
                return "reduce_only_side_mismatch"
            if request.volume_lots > position.volume_lots:
                return "reduce_only_volume_exceeds_position"
        return None

    def _validate_pending_protection(self, request: OrderRequest) -> None:
        if request.price_ticks is None:
            return
        side = PositionSide.LONG if request.side is Side.BUY else PositionSide.SHORT
        self._validate_position_protection(
            side.value,
            request.price_ticks,
            request.stop_loss_ticks,
            request.take_profit_ticks,
            self.symbol_profiles[request.symbol],
        )

    def _validate_position_protection(
        self,
        side: str,
        entry_ticks: int,
        stop_loss_ticks: int | None,
        take_profit_ticks: int | None,
        profile: SymbolProfile,
    ) -> None:
        minimum = points_to_ticks(profile.stops_level_points, profile)
        if side == PositionSide.LONG.value:
            if stop_loss_ticks is not None and stop_loss_ticks >= entry_ticks:
                raise ValueError("long stop loss must be below entry")
            if take_profit_ticks is not None and take_profit_ticks <= entry_ticks:
                raise ValueError("long take profit must be above entry")
        else:
            if stop_loss_ticks is not None and stop_loss_ticks <= entry_ticks:
                raise ValueError("short stop loss must be above entry")
            if take_profit_ticks is not None and take_profit_ticks >= entry_ticks:
                raise ValueError("short take profit must be below entry")
        if stop_loss_ticks is not None and abs(entry_ticks - stop_loss_ticks) < minimum:
            raise ValueError("stop loss violates stops_level_points")
        if take_profit_ticks is not None and abs(entry_ticks - take_profit_ticks) < minimum:
            raise ValueError("take profit violates stops_level_points")

    def _validate_bar_sequence(self, bar: Bar) -> None:
        if bar.timeframe is not self.run_config.execution_timeframe:
            raise BrokerConfigurationError("broker processes execution timeframe bars only")
        previous = self.state.last_bar_sequence.get(bar.symbol)
        if previous is not None and bar.sequence <= previous:
            raise BrokerConfigurationError("bar sequence must increase monotonically")
        previous_close = self.state.last_bar_close_time_ns.get(bar.symbol)
        if previous_close is not None and bar.open_time_ns < previous_close:
            raise BrokerConfigurationError("bar time must increase monotonically")
        if bar.symbol not in self.symbol_profiles:
            raise BrokerConfigurationError(f"unknown bar symbol: {bar.symbol}")

    def _expire_orders(
        self,
        bar: Bar,
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        for order in self._orders_with_status({OrderStatus.ACCEPTED, OrderStatus.ACTIVE}):
            expiration = order.request.expiration_time_ns
            if expiration is None or expiration > bar.open_time_ns:
                continue
            expired = transition_order(order, OrderStatus.EXPIRED, bar.open_time_ns)
            self.state.orders[order.order_id] = expired
            events.append(self._emit(EventType.ORDER_EXPIRED, bar.open_time_ns, expired))

    def _activate_orders(
        self,
        bar: Bar,
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        for order in self._orders_with_status({OrderStatus.ACCEPTED}):
            if order.request.symbol != bar.symbol:
                continue
            if bar.open_time_ns < order.request.created_time_ns:
                continue
            active = transition_order(order, OrderStatus.ACTIVE, bar.open_time_ns)
            self.state.orders[order.order_id] = active
            events.append(self._emit(EventType.ORDER_ACTIVATED, bar.open_time_ns, active))

    def _active_orders(self, symbol: str) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self._orders_with_status({OrderStatus.ACTIVE})
            if order.request.symbol == symbol
            and "broker_protection" not in order.request.tags
            and "broker_exit" not in order.request.tags
        )

    def _orders_with_status(self, statuses: set[OrderStatus]) -> tuple[Order, ...]:
        return tuple(
            self.state.orders[key]
            for key in sorted(self.state.orders)
            if self.state.orders[key].status in statuses
        )

    def _order_fill_decision(
        self,
        order: Order,
        resolved: ResolvedBar,
    ) -> FillDecision | None:
        request = order.request
        side_bar = resolved.ask if request.side is Side.BUY else resolved.bid
        if request.order_type is OrderType.MARKET:
            base = side_bar.open_ticks
            slippage = points_to_ticks(
                self.run_config.execution.slippage.market_order_points,
                self.symbol_profiles[request.symbol],
            )
            actual = base + slippage if request.side is Side.BUY else base - slippage
            return FillDecision(actual, base, abs(actual - base), "market_open", True)
        trigger = cast(int, request.price_ticks)
        if request.order_type is OrderType.LIMIT:
            if request.side is Side.BUY and side_bar.low_ticks > trigger:
                return None
            if request.side is Side.SELL and side_bar.high_ticks < trigger:
                return None
            at_open = (
                side_bar.open_ticks <= trigger
                if request.side is Side.BUY
                else side_bar.open_ticks >= trigger
            )
            base = side_bar.open_ticks if at_open else trigger
            configured = points_to_ticks(
                self.run_config.execution.slippage.limit_order_points,
                self.symbol_profiles[request.symbol],
            )
            if request.side is Side.BUY:
                actual = min(base + configured, trigger)
            else:
                actual = max(base - configured, trigger)
            return FillDecision(actual, base, abs(actual - base), "limit_fill", at_open)
        if request.side is Side.BUY and side_bar.high_ticks < trigger:
            return None
        if request.side is Side.SELL and side_bar.low_ticks > trigger:
            return None
        at_open = (
            side_bar.open_ticks >= trigger
            if request.side is Side.BUY
            else side_bar.open_ticks <= trigger
        )
        base = side_bar.open_ticks if at_open else trigger
        configured = points_to_ticks(
            self.run_config.execution.slippage.stop_order_points,
            self.symbol_profiles[request.symbol],
        )
        actual = base + configured if request.side is Side.BUY else base - configured
        return FillDecision(actual, base, abs(actual - base), "stop_fill", at_open)

    def _execute_order(
        self,
        order: Order,
        decision: FillDecision,
        spread_ticks: int,
        time_ns: int,
        fills: list[Fill],
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> tuple[str, ...]:
        request = order.request
        profile = self.symbol_profiles[request.symbol]
        try:
            self._validate_position_protection(
                PositionSide.LONG.value if request.side is Side.BUY else PositionSide.SHORT.value,
                decision.price_ticks,
                request.stop_loss_ticks,
                request.take_profit_ticks,
                profile,
            )
            self._validate_execution_capacity(request, decision.price_ticks)
        except (ValueError, OrderRejectedError) as exc:
            rejected = transition_order(
                order,
                OrderStatus.REJECTED,
                time_ns,
                rejection_reason=str(exc),
            )
            self.state.orders[order.order_id] = rejected
            events.append(self._emit(EventType.ORDER_REJECTED, time_ns, rejected))
            return ()
        commission = commission_cost(
            self.run_config.execution.commission,
            request.side,
            request.volume_lots,
            decision.price_ticks,
            profile,
        )
        spread = spread_cost(
            spread_ticks,
            request.volume_lots,
            profile,
        )
        slippage = slippage_cost(
            decision.slippage_ticks,
            request.volume_lots,
            profile,
        )
        fill = Fill(
            fill_id=self._ids.next("fill"),
            order_id=order.order_id,
            run_id=request.run_id,
            symbol=request.symbol,
            side=request.side,
            time_ns=time_ns,
            price_ticks=decision.price_ticks,
            volume_lots=request.volume_lots,
            commission=commission,
            spread_cost=spread,
            slippage_cost=slippage,
        )
        filled = apply_fill(order, fill)
        self.state.orders[order.order_id] = filled
        self.state.fills.append(fill)
        fills.append(fill)
        self.state.account.balance -= commission
        events.append(
            self._emit(
                EventType.ORDER_FILLED,
                time_ns,
                fill,
                extra={"fill_reason": decision.reason},
            )
        )
        opened = self._apply_fill_to_portfolio(fill, filled, trades, events)
        return opened

    def _validate_execution_capacity(self, request: OrderRequest, price_ticks: int) -> None:
        if request.reduce_only:
            position = self.state.positions.get(cast(str, request.position_id))
            if position is None:
                raise OrderRejectedError("reduce-only position does not exist")
            if request.volume_lots > position.volume_lots:
                raise OrderRejectedError("reduce-only volume exceeds current position")
            expected_side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
            if request.side is not expected_side:
                raise OrderRejectedError("reduce-only side does not close the position")
            return
        side = PositionSide.LONG if request.side is Side.BUY else PositionSide.SHORT
        if side is PositionSide.LONG and not self.run_config.risk.allow_long:
            raise OrderRejectedError("long trading is disabled")
        if side is PositionSide.SHORT and not self.run_config.risk.allow_short:
            raise OrderRejectedError("short trading is disabled")
        opening_volume = self._opening_volume(request)
        if opening_volume == 0:
            return
        positions = tuple(self.state.positions.values())
        symbol_positions = tuple(item for item in positions if item.symbol == request.symbol)
        if self.run_config.account.position_mode is PositionMode.HEDGING:
            same_side = tuple(item for item in symbol_positions if item.side == side.value)
            if same_side and not self.run_config.risk.allow_pyramiding:
                raise OrderRejectedError("pyramiding is disabled")
            if len(positions) >= self.run_config.risk.max_open_positions:
                raise OrderRejectedError("max_open_positions exceeded")
            if len(symbol_positions) >= self.run_config.risk.max_symbol_positions:
                raise OrderRejectedError("max_symbol_positions exceeded")
        else:
            current = self._net_position(request.symbol)
            same_side = current is not None and current.side == side.value
            if same_side and not self.run_config.risk.allow_pyramiding:
                raise OrderRejectedError("pyramiding is disabled")
        margin = required_margin(
            price_ticks,
            opening_volume,
            self.symbol_profiles[request.symbol],
            self.run_config.account.leverage,
        )
        current_margin = sum((item.margin for item in positions), start=ZERO)
        projected_margin = current_margin + margin
        equity = self.state.account.equity
        if equity <= 0 or projected_margin > equity:
            raise OrderRejectedError("insufficient_free_margin")
        usage = projected_margin / equity * HUNDRED
        if usage > self.run_config.risk.max_margin_usage_percent:
            raise OrderRejectedError("max_margin_usage_percent exceeded")

    def _opening_volume(self, request: OrderRequest) -> Decimal:
        if self.run_config.account.position_mode is PositionMode.HEDGING:
            return ZERO if request.reduce_only else request.volume_lots
        position = self._net_position(request.symbol)
        if position is None:
            return ZERO if request.reduce_only else request.volume_lots
        same_side = (request.side is Side.BUY and position.side == PositionSide.LONG.value) or (
            request.side is Side.SELL and position.side == PositionSide.SHORT.value
        )
        if same_side:
            return request.volume_lots
        return max(ZERO, request.volume_lots - position.volume_lots)

    def _apply_fill_to_portfolio(
        self,
        fill: Fill,
        order: Order,
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> tuple[str, ...]:
        if self.run_config.account.position_mode is PositionMode.HEDGING:
            return self._apply_hedging_fill(fill, order, trades, events)
        return self._apply_netting_fill(fill, order, trades, events)

    def _apply_hedging_fill(
        self,
        fill: Fill,
        order: Order,
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> tuple[str, ...]:
        if order.request.reduce_only:
            position = self._require_position(cast(str, order.request.position_id))
            self._close_position(
                position,
                fill.volume_lots,
                fill.price_ticks,
                fill.time_ns,
                fill.order_id,
                fill.commission,
                fill.spread_cost,
                fill.slippage_cost,
                "strategy_exit",
                False,
                trades,
                events,
            )
            return ()
        position = self._new_position(
            order,
            fill.volume_lots,
            fill.price_ticks,
            fill.commission,
            fill.spread_cost,
            fill.slippage_cost,
        )
        self.state.positions[position.position_id] = position
        events.append(
            self._emit(EventType.POSITION_OPENED, fill.time_ns, self._position_contract(position))
        )
        self._sync_protection_orders(position, fill.time_ns, events)
        return (position.position_id,)

    def _apply_netting_fill(
        self,
        fill: Fill,
        order: Order,
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> tuple[str, ...]:
        position = self._net_position(fill.symbol)
        if position is None:
            if order.request.reduce_only:
                raise PositionNotFoundError("net position does not exist")
            created = self._new_position(
                order,
                fill.volume_lots,
                fill.price_ticks,
                fill.commission,
                fill.spread_cost,
                fill.slippage_cost,
            )
            self.state.positions[created.position_id] = created
            events.append(
                self._emit(
                    EventType.POSITION_OPENED,
                    fill.time_ns,
                    self._position_contract(created),
                )
            )
            self._sync_protection_orders(created, fill.time_ns, events)
            return (created.position_id,)
        same_side = (fill.side is Side.BUY and position.side == PositionSide.LONG.value) or (
            fill.side is Side.SELL and position.side == PositionSide.SHORT.value
        )
        if same_side:
            if order.request.reduce_only:
                raise OrderRejectedError("reduce-only order cannot increase a net position")
            self._increase_net_position(position, order, fill)
            self._sync_protection_orders(position, fill.time_ns, events)
            events.append(
                self._emit(
                    EventType.POSITION_UPDATED,
                    fill.time_ns,
                    self._position_contract(position),
                )
            )
            return ()
        close_volume = min(fill.volume_lots, position.volume_lots)
        close_ratio = close_volume / fill.volume_lots
        close_commission = fill.commission * close_ratio
        close_spread = fill.spread_cost * close_ratio
        close_slippage = fill.slippage_cost * close_ratio
        self._close_position(
            position,
            close_volume,
            fill.price_ticks,
            fill.time_ns,
            fill.order_id,
            close_commission,
            close_spread,
            close_slippage,
            "netting_reduction",
            False,
            trades,
            events,
        )
        remainder = fill.volume_lots - close_volume
        if remainder == 0 or order.request.reduce_only:
            return ()
        open_ratio = remainder / fill.volume_lots
        created = self._new_position(
            order,
            remainder,
            fill.price_ticks,
            fill.commission * open_ratio,
            fill.spread_cost * open_ratio,
            fill.slippage_cost * open_ratio,
        )
        self.state.positions[created.position_id] = created
        events.append(
            self._emit(EventType.POSITION_OPENED, fill.time_ns, self._position_contract(created))
        )
        self._sync_protection_orders(created, fill.time_ns, events)
        return (created.position_id,)

    def _new_position(
        self,
        order: Order,
        volume: Decimal,
        price_ticks: int,
        commission: Decimal,
        spread: Decimal,
        slippage: Decimal,
    ) -> PositionState:
        request = order.request
        profile = self.symbol_profiles[request.symbol]
        margin = required_margin(
            price_ticks,
            volume,
            profile,
            self.run_config.account.leverage,
        )
        initial_risk = None
        if request.stop_loss_ticks is not None:
            initial_risk = money_for_ticks(
                Decimal(abs(price_ticks - request.stop_loss_ticks)),
                volume,
                profile,
                favorable=False,
            )
        return PositionState(
            position_id=self._ids.next("pos"),
            run_id=request.run_id,
            strategy_instance_id=request.strategy_instance_id,
            symbol=request.symbol,
            side=(PositionSide.LONG if request.side is Side.BUY else PositionSide.SHORT).value,
            volume_lots=volume,
            average_entry_price_ticks=Decimal(price_ticks),
            opened_time_ns=cast(int, order.terminal_time_ns),
            entry_order_id=order.order_id,
            stop_loss_ticks=request.stop_loss_ticks,
            take_profit_ticks=request.take_profit_ticks,
            entry_commission=commission,
            entry_spread_cost=spread,
            entry_slippage_cost=slippage,
            margin=margin,
            initial_risk=initial_risk,
            current_price_ticks=price_ticks,
            last_update_time_ns=cast(int, order.terminal_time_ns),
        )

    def _increase_net_position(self, position: PositionState, order: Order, fill: Fill) -> None:
        old_volume = position.volume_lots
        new_volume = old_volume + fill.volume_lots
        position.average_entry_price_ticks = (
            position.average_entry_price_ticks * old_volume
            + Decimal(fill.price_ticks) * fill.volume_lots
        ) / new_volume
        position.volume_lots = new_volume
        position.entry_commission += fill.commission
        position.entry_spread_cost += fill.spread_cost
        position.entry_slippage_cost += fill.slippage_cost
        position.margin += required_margin(
            fill.price_ticks,
            fill.volume_lots,
            self.symbol_profiles[position.symbol],
            self.run_config.account.leverage,
        )
        if order.request.stop_loss_ticks is not None:
            position.stop_loss_ticks = order.request.stop_loss_ticks
        if order.request.take_profit_ticks is not None:
            position.take_profit_ticks = order.request.take_profit_ticks
        if position.stop_loss_ticks is not None:
            position.initial_risk = money_for_ticks(
                abs(position.average_entry_price_ticks - Decimal(position.stop_loss_ticks)),
                position.volume_lots,
                self.symbol_profiles[position.symbol],
                favorable=False,
            )
        position.last_update_time_ns = fill.time_ns

    def _sync_protection_orders(
        self,
        position: PositionState,
        time_ns: int,
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        self._cancel_protection_order(position.stop_order_id, time_ns, events)
        self._cancel_protection_order(position.take_profit_order_id, time_ns, events)
        position.stop_order_id = None
        position.take_profit_order_id = None
        if position.stop_loss_ticks is not None:
            position.stop_order_id = self._create_protection_order(
                position,
                time_ns,
                "stop_loss",
                position.stop_loss_ticks,
                OrderType.STOP,
                events,
            )
        if position.take_profit_ticks is not None:
            position.take_profit_order_id = self._create_protection_order(
                position,
                time_ns,
                "take_profit",
                position.take_profit_ticks,
                OrderType.LIMIT,
                events,
            )

    def _create_protection_order(
        self,
        position: PositionState,
        time_ns: int,
        reason: str,
        price_ticks: int,
        order_type: OrderType,
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> str:
        side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
        request = OrderRequest(
            client_order_id=self._ids.next("protection_client"),
            run_id=position.run_id,
            strategy_instance_id=position.strategy_instance_id,
            symbol=position.symbol,
            side=side,
            order_type=order_type,
            volume_lots=position.volume_lots,
            created_time_ns=time_ns,
            price_ticks=price_ticks,
            reduce_only=True,
            position_id=position.position_id,
            tags={"broker_protection": reason},
        )
        created = Order(order_id=self._ids.next("ord"), request=request)
        accepted = transition_order(created, OrderStatus.ACCEPTED, time_ns)
        active = transition_order(accepted, OrderStatus.ACTIVE, time_ns)
        self.state.orders[active.order_id] = active
        self._client_order_ids.add(request.client_order_id)
        events.append(self._emit(EventType.ORDER_CREATED, time_ns, created))
        events.append(self._emit(EventType.ORDER_ACCEPTED, time_ns, accepted))
        events.append(self._emit(EventType.ORDER_ACTIVATED, time_ns, active))
        return active.order_id

    def _create_synthetic_exit_order(
        self,
        position: PositionState,
        time_ns: int,
        reason: str,
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> Order:
        side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
        request = OrderRequest(
            client_order_id=self._ids.next("broker_exit_client"),
            run_id=position.run_id,
            strategy_instance_id=position.strategy_instance_id,
            symbol=position.symbol,
            side=side,
            order_type=OrderType.MARKET,
            volume_lots=position.volume_lots,
            created_time_ns=time_ns,
            reduce_only=True,
            position_id=position.position_id,
            tags={"broker_exit": reason},
        )
        created = Order(order_id=self._ids.next("ord"), request=request)
        accepted = transition_order(created, OrderStatus.ACCEPTED, time_ns)
        active = transition_order(accepted, OrderStatus.ACTIVE, time_ns)
        self.state.orders[active.order_id] = active
        self._client_order_ids.add(request.client_order_id)
        events.append(self._emit(EventType.ORDER_CREATED, time_ns, created))
        events.append(self._emit(EventType.ORDER_ACCEPTED, time_ns, accepted))
        events.append(self._emit(EventType.ORDER_ACTIVATED, time_ns, active))
        return active

    def _cancel_protection_order(
        self,
        order_id: str | None,
        time_ns: int,
        events: list[EventEnvelope[dict[str, JsonValue]]],
        exclude_order_id: str | None = None,
    ) -> None:
        if order_id is None or order_id == exclude_order_id:
            return
        order = self.state.orders.get(order_id)
        if order is None or order.status not in {OrderStatus.ACCEPTED, OrderStatus.ACTIVE}:
            return
        cancelled = transition_order(order, OrderStatus.CANCELLED, time_ns)
        self.state.orders[order_id] = cancelled
        events.append(
            self._emit(
                EventType.ORDER_CANCELLED,
                time_ns,
                cancelled,
                extra={"reason": "protection_replaced_or_position_closed"},
            )
        )

    def _process_protections(
        self,
        bar: Bar,
        resolved: ResolvedBar,
        preexisting: set[str],
        intrabar_entries: set[str],
        fills: list[Fill],
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        for position_id in tuple(sorted(self.state.positions)):
            position = self.state.positions.get(position_id)
            if position is None or position.symbol != bar.symbol:
                continue
            if (
                position_id not in preexisting
                and not self.run_config.execution.allow_same_bar_exit_after_open_fill
            ):
                continue
            decision = self._protection_decision(
                position,
                resolved,
                position_id in intrabar_entries,
            )
            if decision is None:
                continue
            protection_order_id = (
                position.stop_order_id
                if decision.reason == "stop_loss"
                else position.take_profit_order_id
            )
            if protection_order_id is None:
                raise BrokerConfigurationError("protection order is missing")
            protection_order = self._require_order(protection_order_id)
            exit_side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
            profile = self.symbol_profiles[position.symbol]
            commission = commission_cost(
                self.run_config.execution.commission,
                exit_side,
                position.volume_lots,
                decision.price_ticks,
                profile,
            )
            spread = spread_cost(
                resolved.spread_ticks,
                position.volume_lots,
                profile,
            )
            slippage = slippage_cost(
                decision.slippage_ticks,
                position.volume_lots,
                profile,
            )
            fill = Fill(
                fill_id=self._ids.next("fill"),
                order_id=protection_order.order_id,
                run_id=position.run_id,
                symbol=position.symbol,
                side=exit_side,
                time_ns=bar.close_time_ns,
                price_ticks=decision.price_ticks,
                volume_lots=position.volume_lots,
                commission=commission,
                spread_cost=spread,
                slippage_cost=slippage,
            )
            filled_order = apply_fill(protection_order, fill)
            self.state.orders[filled_order.order_id] = filled_order
            self.state.fills.append(fill)
            fills.append(fill)
            self.state.account.balance -= commission
            events.append(
                self._emit(
                    EventType.ORDER_FILLED,
                    bar.close_time_ns,
                    fill,
                    extra={"fill_reason": decision.reason},
                )
            )
            self._close_position(
                position,
                position.volume_lots,
                decision.price_ticks,
                bar.close_time_ns,
                fill.order_id,
                commission,
                spread,
                slippage,
                decision.reason,
                decision.ambiguous,
                trades,
                events,
            )

    def _protection_decision(
        self,
        position: PositionState,
        resolved: ResolvedBar,
        intrabar_entry: bool,
    ) -> ProtectionDecision | None:
        side_bar = resolved.bid if position.side == PositionSide.LONG.value else resolved.ask
        stop = position.stop_loss_ticks
        target = position.take_profit_ticks
        if position.side == PositionSide.LONG.value:
            stop_hit = stop is not None and side_bar.low_ticks <= stop
            target_hit = target is not None and side_bar.high_ticks >= target
        else:
            stop_hit = stop is not None and side_bar.high_ticks >= stop
            target_hit = target is not None and side_bar.low_ticks <= target
        if not stop_hit and not target_hit:
            return None
        if intrabar_entry:
            return self._resolve_intrabar_entry_protection(
                position,
                side_bar.open_ticks,
                stop_hit,
                target_hit,
            )
        reason = self._select_protection_reason(
            position,
            side_bar.open_ticks,
            stop_hit,
            target_hit,
        )
        if reason is None:
            return None
        return self._build_protection_decision(
            position,
            side_bar.open_ticks,
            reason,
            stop_hit and target_hit,
        )

    def _resolve_intrabar_entry_protection(
        self,
        position: PositionState,
        open_ticks: int,
        stop_hit: bool,
        target_hit: bool,
    ) -> ProtectionDecision | None:
        policy = self.run_config.execution.intrabar_policy
        if policy is IntrabarPolicy.REJECT_AMBIGUOUS:
            raise AmbiguousBarError("entry and protection ordering is ambiguous")
        if policy in {IntrabarPolicy.CONSERVATIVE, IntrabarPolicy.STOP_FIRST}:
            if stop_hit:
                return self._build_protection_decision(position, open_ticks, "stop_loss", True)
            return None
        if policy in {IntrabarPolicy.OPTIMISTIC, IntrabarPolicy.TARGET_FIRST}:
            if target_hit:
                return self._build_protection_decision(position, open_ticks, "take_profit", True)
            return None
        reason = self._select_protection_reason(
            position,
            open_ticks,
            stop_hit,
            target_hit,
        )
        if reason is None:
            return None
        return self._build_protection_decision(position, open_ticks, reason, True)

    def _select_protection_reason(
        self,
        position: PositionState,
        open_ticks: int,
        stop_hit: bool,
        target_hit: bool,
    ) -> str | None:
        if stop_hit and not target_hit:
            return "stop_loss"
        if target_hit and not stop_hit:
            return "take_profit"
        policy = self.run_config.execution.intrabar_policy
        if policy is IntrabarPolicy.REJECT_AMBIGUOUS:
            raise AmbiguousBarError("stop loss and take profit were touched in one bar")
        if policy in {IntrabarPolicy.CONSERVATIVE, IntrabarPolicy.STOP_FIRST}:
            return "stop_loss"
        if policy in {IntrabarPolicy.OPTIMISTIC, IntrabarPolicy.TARGET_FIRST}:
            return "take_profit"
        stop = cast(int, position.stop_loss_ticks)
        target = cast(int, position.take_profit_ticks)
        stop_distance = abs(open_ticks - stop)
        target_distance = abs(open_ticks - target)
        return "stop_loss" if stop_distance <= target_distance else "take_profit"

    def _build_protection_decision(
        self,
        position: PositionState,
        open_ticks: int,
        reason: str,
        ambiguous: bool,
    ) -> ProtectionDecision:
        exit_side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
        level = cast(
            int,
            position.stop_loss_ticks if reason == "stop_loss" else position.take_profit_ticks,
        )
        is_stop = reason == "stop_loss"
        if position.side == PositionSide.LONG.value:
            gap = open_ticks <= level if is_stop else open_ticks >= level
        else:
            gap = open_ticks >= level if is_stop else open_ticks <= level
        base = open_ticks if gap else level
        points = (
            self.run_config.execution.slippage.stop_order_points
            if is_stop
            else self.run_config.execution.slippage.limit_order_points
        )
        configured = points_to_ticks(points, self.symbol_profiles[position.symbol])
        if is_stop:
            actual = base - configured if exit_side is Side.SELL else base + configured
        elif exit_side is Side.SELL:
            actual = max(base - configured, level)
        else:
            actual = min(base + configured, level)
        return ProtectionDecision(
            price_ticks=actual,
            reference_price_ticks=base,
            slippage_ticks=abs(actual - base),
            reason=reason,
            ambiguous=ambiguous,
        )

    def _close_position(
        self,
        position: PositionState,
        volume: Decimal,
        exit_price_ticks: int,
        time_ns: int,
        exit_order_id: str,
        exit_commission: Decimal,
        exit_spread: Decimal,
        exit_slippage: Decimal,
        reason: str,
        ambiguous: bool,
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        if volume <= 0 or volume > position.volume_lots:
            raise OrderRejectedError("invalid close volume")
        original_volume = position.volume_lots
        ratio = volume / original_volume
        entry_commission = position.entry_commission * ratio
        entry_spread = position.entry_spread_cost * ratio
        entry_slippage = position.entry_slippage_cost * ratio
        swap = position.swap * ratio
        initial_risk = position.initial_risk * ratio if position.initial_risk is not None else None
        mae = position.mae * ratio
        mfe = position.mfe * ratio
        actual_pnl = signed_price_pnl(
            PositionSide(position.side),
            position.average_entry_price_ticks,
            Decimal(exit_price_ticks),
            volume,
            self.symbol_profiles[position.symbol],
        )
        total_commission = entry_commission + exit_commission
        total_spread = entry_spread + exit_spread
        total_slippage = entry_slippage + exit_slippage
        gross_pnl = actual_pnl + total_spread + total_slippage
        net_pnl = gross_pnl - total_commission - total_spread - total_slippage + swap
        realized_r = net_pnl / initial_risk if initial_risk is not None else None
        trade = Trade(
            trade_id=self._ids.next("trade"),
            position_id=position.position_id,
            run_id=position.run_id,
            strategy_instance_id=position.strategy_instance_id,
            symbol=position.symbol,
            side=PositionSide(position.side),
            volume_lots=volume,
            entry_time_ns=position.opened_time_ns,
            exit_time_ns=time_ns,
            entry_price_ticks=position.average_entry_price_ticks,
            exit_price_ticks=Decimal(exit_price_ticks),
            stop_loss_ticks=position.stop_loss_ticks,
            take_profit_ticks=position.take_profit_ticks,
            gross_pnl=gross_pnl,
            commission=total_commission,
            spread_cost=total_spread,
            slippage_cost=total_slippage,
            swap=swap,
            net_pnl=net_pnl,
            initial_risk=initial_risk,
            realized_r_multiple=realized_r,
            mae=mae,
            mfe=mfe,
            intrabar_ambiguous=ambiguous,
            exit_reason=reason,
        )
        closed_contract = Position(
            position_id=position.position_id,
            run_id=position.run_id,
            strategy_instance_id=position.strategy_instance_id,
            symbol=position.symbol,
            side=PositionSide(position.side),
            status=PositionStatus.CLOSED,
            volume_lots=volume,
            average_entry_price_ticks=position.average_entry_price_ticks,
            opened_time_ns=position.opened_time_ns,
            current_price_ticks=exit_price_ticks,
            stop_loss_ticks=position.stop_loss_ticks,
            take_profit_ticks=position.take_profit_ticks,
            closed_time_ns=time_ns,
            realized_pnl=net_pnl,
            unrealized_pnl=ZERO,
            commission=total_commission,
            spread_cost=total_spread,
            slippage_cost=total_slippage,
            swap=swap,
        )
        self.state.account.balance += actual_pnl + swap
        self.state.trades.append(trade)
        trades.append(trade)
        position.volume_lots -= volume
        position.entry_commission -= entry_commission
        position.entry_spread_cost -= entry_spread
        position.entry_slippage_cost -= entry_slippage
        position.swap -= swap
        position.margin *= Decimal("1") - ratio
        if position.initial_risk is not None:
            position.initial_risk -= initial_risk or ZERO
        position.mae *= Decimal("1") - ratio
        position.mfe *= Decimal("1") - ratio
        if position.volume_lots == 0:
            self._cancel_protection_order(
                position.stop_order_id,
                time_ns,
                events,
                exclude_order_id=exit_order_id,
            )
            self._cancel_protection_order(
                position.take_profit_order_id,
                time_ns,
                events,
                exclude_order_id=exit_order_id,
            )
            del self.state.positions[position.position_id]
            event_type = (
                EventType.POSITION_LIQUIDATED if reason == "stop_out" else EventType.POSITION_CLOSED
            )
            events.append(
                self._emit(
                    event_type,
                    time_ns,
                    closed_contract,
                    extra={"trade": self._json(trade)},
                )
            )
        else:
            position.last_update_time_ns = time_ns
            self._sync_protection_orders(position, time_ns, events)
            events.append(
                self._emit(EventType.POSITION_UPDATED, time_ns, self._position_contract(position))
            )

    def _update_positions_for_bar(self, bar: Bar, resolved: ResolvedBar) -> None:
        for position in self.state.positions.values():
            if position.symbol != bar.symbol:
                continue
            profile = self.symbol_profiles[position.symbol]
            if position.side == PositionSide.LONG.value:
                favorable_ticks = (
                    Decimal(resolved.bid.high_ticks) - position.average_entry_price_ticks
                )
                adverse_ticks = position.average_entry_price_ticks - Decimal(resolved.bid.low_ticks)
                mark = resolved.bid.close_ticks
            else:
                favorable_ticks = position.average_entry_price_ticks - Decimal(
                    resolved.ask.low_ticks
                )
                adverse_ticks = (
                    Decimal(resolved.ask.high_ticks) - position.average_entry_price_ticks
                )
                mark = resolved.ask.close_ticks
            if favorable_ticks > 0:
                position.mfe = max(
                    position.mfe,
                    money_for_ticks(favorable_ticks, position.volume_lots, profile, True),
                )
            if adverse_ticks > 0:
                position.mae = max(
                    position.mae,
                    money_for_ticks(adverse_ticks, position.volume_lots, profile, False),
                )
            position.current_price_ticks = mark
            position.last_update_time_ns = bar.close_time_ns

    def _revalue_account(self, time_ns: int, resolved: ResolvedBar | None = None) -> None:
        del time_ns, resolved
        floating = ZERO
        margin = ZERO
        for position in self.state.positions.values():
            profile = self.symbol_profiles[position.symbol]
            last = self._last_resolved.get(position.symbol)
            if last is not None:
                mark = (
                    last.bid.close_ticks
                    if position.side == PositionSide.LONG.value
                    else last.ask.close_ticks
                )
            elif position.current_price_ticks is not None:
                mark = position.current_price_ticks
            else:
                mark = int(position.average_entry_price_ticks)
            floating += (
                signed_price_pnl(
                    PositionSide(position.side),
                    position.average_entry_price_ticks,
                    Decimal(mark),
                    position.volume_lots,
                    profile,
                )
                + position.swap
            )
            position_margin = required_margin(
                mark,
                position.volume_lots,
                profile,
                self.run_config.account.leverage,
            )
            position.margin = position_margin
            margin += position_margin
        account = self.state.account
        account.floating_pnl = floating
        account.margin = margin
        account.equity = account.balance + floating
        account.free_margin = account.equity - margin
        account.margin_level_percent = account.equity / margin * HUNDRED if margin > 0 else None
        account.peak_equity = max(account.peak_equity, account.equity)
        account.drawdown_amount = max(ZERO, account.peak_equity - account.equity)
        account.drawdown_percent = (
            account.drawdown_amount / account.peak_equity * HUNDRED
            if account.peak_equity > 0
            else ZERO
        )

    def _process_margin_state(
        self,
        bar: Bar,
        resolved: ResolvedBar,
        fills: list[Fill],
        trades: list[Trade],
        events: list[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        account = self.state.account
        level = account.margin_level_percent
        if level is None:
            account.margin_call_active = False
            return
        margin_call = level <= self.run_config.account.margin_call_level_percent
        if margin_call and not account.margin_call_active:
            events.append(
                self._emit(
                    EventType.ACCOUNT_MARGIN_CALL,
                    bar.close_time_ns,
                    self._snapshot(bar.close_time_ns, self._events.sequence + 1),
                )
            )
        account.margin_call_active = margin_call
        if level > self.run_config.account.stop_out_level_percent:
            return
        events.append(
            self._emit(
                EventType.ACCOUNT_STOP_OUT,
                bar.close_time_ns,
                self._snapshot(bar.close_time_ns, self._events.sequence + 1),
            )
        )
        while self.state.positions:
            current = self.state.account.margin_level_percent
            if current is None or current > self.run_config.account.stop_out_level_percent:
                break
            position = self._worst_position()
            side = Side.SELL if position.side == PositionSide.LONG.value else Side.BUY
            position_market = self._last_resolved[position.symbol]
            side_bar = position_market.bid if side is Side.SELL else position_market.ask
            base = side_bar.close_ticks
            slip_ticks = points_to_ticks(
                self.run_config.execution.slippage.market_order_points,
                self.symbol_profiles[position.symbol],
            )
            actual = base - slip_ticks if side is Side.SELL else base + slip_ticks
            profile = self.symbol_profiles[position.symbol]
            commission = commission_cost(
                self.run_config.execution.commission,
                side,
                position.volume_lots,
                actual,
                profile,
            )
            spread = spread_cost(
                position_market.spread_ticks,
                position.volume_lots,
                profile,
            )
            slippage = slippage_cost(slip_ticks, position.volume_lots, profile)
            exit_order = self._create_synthetic_exit_order(
                position,
                bar.close_time_ns,
                "stop_out",
                events,
            )
            fill = Fill(
                fill_id=self._ids.next("fill"),
                order_id=exit_order.order_id,
                run_id=position.run_id,
                symbol=position.symbol,
                side=side,
                time_ns=bar.close_time_ns,
                price_ticks=actual,
                volume_lots=position.volume_lots,
                commission=commission,
                spread_cost=spread,
                slippage_cost=slippage,
            )
            filled_order = apply_fill(exit_order, fill)
            self.state.orders[filled_order.order_id] = filled_order
            self.state.account.balance -= commission
            self.state.fills.append(fill)
            fills.append(fill)
            events.append(
                self._emit(
                    EventType.ORDER_FILLED,
                    bar.close_time_ns,
                    fill,
                    extra={"fill_reason": "stop_out"},
                )
            )
            self._close_position(
                position,
                position.volume_lots,
                actual,
                bar.close_time_ns,
                fill.order_id,
                commission,
                spread,
                slippage,
                "stop_out",
                False,
                trades,
                events,
            )
            self._revalue_account(bar.close_time_ns, resolved)

    def _apply_negative_balance_protection(
        self,
        time_ns: int,
        resolved: ResolvedBar,
    ) -> None:
        if self.state.positions or self.run_config.account.allow_negative_balance:
            return
        if self.state.account.balance < 0:
            self.state.account.balance = ZERO
        self._revalue_account(time_ns, resolved)
        self.state.account.margin_call_active = False

    def _worst_position(self) -> PositionState:
        def unrealized(position: PositionState) -> Decimal:
            mark = position.current_price_ticks or int(position.average_entry_price_ticks)
            return signed_price_pnl(
                PositionSide(position.side),
                position.average_entry_price_ticks,
                Decimal(mark),
                position.volume_lots,
                self.symbol_profiles[position.symbol],
            )

        return min(
            self.state.positions.values(),
            key=lambda item: (unrealized(item), item.position_id),
        )

    def _snapshot(
        self,
        timestamp_ns: int,
        sequence: int | None = None,
    ) -> AccountSnapshot:
        account = self.state.account
        return AccountSnapshot(
            run_id=self.run_config.run_id,
            timestamp_ns=timestamp_ns,
            sequence=self._events.sequence if sequence is None else sequence,
            currency=self.run_config.account.currency,
            balance=account.balance,
            equity=account.equity,
            margin=account.margin,
            free_margin=account.free_margin,
            margin_level_percent=account.margin_level_percent,
            floating_pnl=account.floating_pnl,
            peak_equity=account.peak_equity,
            drawdown_amount=account.drawdown_amount,
            drawdown_percent=account.drawdown_percent,
        )

    def _position_contract(self, state: PositionState) -> Position:
        current_price = state.current_price_ticks or int(state.average_entry_price_ticks)
        unrealized = (
            signed_price_pnl(
                PositionSide(state.side),
                state.average_entry_price_ticks,
                Decimal(current_price),
                state.volume_lots,
                self.symbol_profiles[state.symbol],
            )
            + state.swap
        )
        return Position(
            position_id=state.position_id,
            run_id=state.run_id,
            strategy_instance_id=state.strategy_instance_id,
            symbol=state.symbol,
            side=PositionSide(state.side),
            status=PositionStatus.OPEN,
            volume_lots=state.volume_lots,
            average_entry_price_ticks=state.average_entry_price_ticks,
            opened_time_ns=state.opened_time_ns,
            current_price_ticks=state.current_price_ticks,
            stop_loss_ticks=state.stop_loss_ticks,
            take_profit_ticks=state.take_profit_ticks,
            realized_pnl=ZERO,
            unrealized_pnl=unrealized,
            commission=state.entry_commission,
            spread_cost=state.entry_spread_cost,
            slippage_cost=state.entry_slippage_cost,
            swap=state.swap,
        )

    def _net_position(self, symbol: str) -> PositionState | None:
        positions = [item for item in self.state.positions.values() if item.symbol == symbol]
        if len(positions) > 1:
            raise BrokerConfigurationError(
                "netting mode contains multiple positions for one symbol"
            )
        return positions[0] if positions else None

    def _require_order(self, order_id: str) -> Order:
        try:
            return self.state.orders[order_id]
        except KeyError as exc:
            raise OrderNotFoundError(f"order not found: {order_id}") from exc

    def _require_position(self, position_id: str) -> PositionState:
        try:
            return self.state.positions[position_id]
        except KeyError as exc:
            raise PositionNotFoundError(f"position not found: {position_id}") from exc

    def _require_profile(self, symbol: str) -> SymbolProfile:
        try:
            return self.symbol_profiles[symbol]
        except KeyError as exc:
            raise BrokerConfigurationError(f"profile not found for {symbol}") from exc

    def _emit(
        self,
        event_type: EventType,
        time_ns: int,
        model: BaseModel,
        extra: dict[str, JsonValue] | None = None,
    ) -> EventEnvelope[dict[str, JsonValue]]:
        payload = self._json(model)
        if extra:
            payload.update(extra)
        strategy_instance_id = getattr(model, "strategy_instance_id", None)
        symbol = getattr(model, "symbol", None)
        event = self._events.create(
            event_type,
            time_ns,
            payload,
            strategy_instance_id=strategy_instance_id,
            symbol=symbol,
        )
        self.state.events.append(event)
        return event

    @staticmethod
    def _json(model: BaseModel) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], model.model_dump(mode="json"))

    def _result(
        self,
        events: Iterable[EventEnvelope[dict[str, JsonValue]]] = (),
        fills: Iterable[Fill] = (),
        trades: Iterable[Trade] = (),
        snapshot: AccountSnapshot | None = None,
    ) -> BrokerResult:
        return BrokerResult(
            events=tuple(events),
            fills=tuple(fills),
            trades=tuple(trades),
            positions=self.open_positions,
            account_snapshot=snapshot,
        )
