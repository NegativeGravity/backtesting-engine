from enum import StrEnum


class DatasetSource(StrEnum):
    MT5_CSV = "mt5_csv"


class PriceBasis(StrEnum):
    BID = "bid"
    ASK = "ask"
    MID = "mid"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class PositionMode(StrEnum):
    NETTING = "netting"
    HEDGING = "hedging"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    CREATED = "created"
    ACCEPTED = "accepted"
    ACTIVE = "active"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(StrEnum):
    GTC = "gtc"
    DAY = "day"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SignalExecutionPolicy(StrEnum):
    NEXT_BAR_OPEN = "next_bar_open"


class PendingOrderActivationPolicy(StrEnum):
    NEXT_BAR = "next_bar"


class IntrabarPolicy(StrEnum):
    CONSERVATIVE = "conservative"
    OPTIMISTIC = "optimistic"
    NEAREST_TO_OPEN = "nearest_to_open"
    STOP_FIRST = "stop_first"
    TARGET_FIRST = "target_first"
    REJECT_AMBIGUOUS = "reject_ambiguous"


class GapPolicy(StrEnum):
    MARKETABLE_OPEN = "marketable_open"


class CommissionMode(StrEnum):
    NONE = "none"
    FIXED_PER_ORDER = "fixed_per_order"
    PER_LOT_PER_SIDE = "per_lot_per_side"
    PER_LOT_ROUND_TURN = "per_lot_round_turn"
    PERCENTAGE_OF_NOTIONAL = "percentage_of_notional"


class SpreadMode(StrEnum):
    FIXED = "fixed"


class SlippageMode(StrEnum):
    FIXED = "fixed"


class HigherTimeframeAccess(StrEnum):
    CLOSED_ONLY = "closed_only"
    FORMING_ALLOWED = "forming_allowed"


class PositionSizingMode(StrEnum):
    FIXED_LOT = "fixed_lot"
    RISK_PERCENT = "risk_percent"
    FIXED_CASH_RISK = "fixed_cash_risk"
    STRATEGY_DEFINED = "strategy_defined"


class RunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class CalculationMode(StrEnum):
    FOREX = "forex"
    CFD = "cfd"
    CFD_INDEX = "cfd_index"
    FUTURES = "futures"


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_PROGRESS = "run.progress"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    BAR_OPENED = "market.bar_opened"
    BAR_CLOSED = "market.bar_closed"
    ORDER_CREATED = "order.created"
    ORDER_ACCEPTED = "order.accepted"
    ORDER_ACTIVATED = "order.activated"
    ORDER_PARTIALLY_FILLED = "order.partially_filled"
    ORDER_FILLED = "order.filled"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_MODIFIED = "order.modified"
    ORDER_REJECTED = "order.rejected"
    ORDER_EXPIRED = "order.expired"
    POSITION_OPENED = "position.opened"
    POSITION_UPDATED = "position.updated"
    POSITION_CLOSED = "position.closed"
    POSITION_LIQUIDATED = "position.liquidated"
    ACCOUNT_UPDATED = "account.updated"
    ACCOUNT_MARGIN_CALL = "account.margin_call"
    ACCOUNT_STOP_OUT = "account.stop_out"
    CHART_COMMAND = "chart.command"


class ChartSeriesKind(StrEnum):
    LINE = "line"
    AREA = "area"
    HISTOGRAM = "histogram"
    CANDLESTICK = "candlestick"


class ChartLineStyle(StrEnum):
    SOLID = "solid"
    DASHED = "dashed"
    DOTTED = "dotted"


class ChartMarkerShape(StrEnum):
    ARROW_UP = "arrow_up"
    ARROW_DOWN = "arrow_down"
    CIRCLE = "circle"
    SQUARE = "square"


class ChartMarkerPosition(StrEnum):
    ABOVE_BAR = "above_bar"
    BELOW_BAR = "below_bar"
    IN_BAR = "in_bar"


class ChartCommandType(StrEnum):
    DECLARE_PANE = "declare_pane"
    DECLARE_SERIES = "declare_series"
    APPEND_SERIES_POINT = "append_series_point"
    UPSERT_DRAWING = "upsert_drawing"
    DELETE_DRAWING = "delete_drawing"
    CLEAR_LAYER = "clear_layer"


class ChartDrawingKind(StrEnum):
    TREND_LINE = "trend_line"
    HORIZONTAL_LINE = "horizontal_line"
    RECTANGLE = "rectangle"
    MARKER = "marker"
    LABEL = "label"
    RISK_REWARD = "risk_reward"


class DataIssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TrailingBarPolicy(StrEnum):
    MARK_INCOMPLETE = "mark_incomplete"
    DROP = "drop"
    REJECT = "reject"


class CacheMode(StrEnum):
    REUSE = "reuse"
    REFRESH = "refresh"
    READ_ONLY = "read_only"
