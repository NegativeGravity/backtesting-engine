export type Timeframe = "M1" | "M2" | "M3" | "M4" | "M5" | "M6" | "M10" | "M12" | "M15" | "M20" | "M30" | "H1" | "H2" | "H3" | "H4" | "H6" | "H8" | "H12" | "D1" | "W1" | "MN1";

export interface ReplayMetrics {
  initial_balance: string;
  final_balance: string;
  final_equity: string;
  gross_pnl: string;
  net_pnl: string;
  commission: string;
  spread_cost: string;
  slippage_cost: string;
  swap: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  long_trades: number;
  short_trades: number;
  win_rate: string;
  profit_factor: string | null;
  average_r_multiple: string | null;
  max_drawdown_amount: string;
  max_drawdown_percent: string;
}

export interface ReplayRunDescriptor {
  run_id: string;
  name: string;
  strategy_id: string;
  strategy_instance_id: string;
  dataset_id: string;
  default_symbol: string;
  default_timeframe: Timeframe;
  execution_timeframe: Timeframe;
  available_symbols: string[];
  available_timeframes: Timeframe[];
  start_time_ns: number;
  end_time_ns: number;
  metrics: ReplayMetrics;
}

export interface ReplayCatalog {
  runs: ReplayRunDescriptor[];
}

export interface ReplayBar {
  symbol: string;
  timeframe: Timeframe;
  sequence: number;
  open_time_ns: number;
  close_time_ns: number;
  open: string;
  high: string;
  low: string;
  close: string;
  tick_volume: number;
  real_volume: string;
  source_spread_points: number;
  is_complete: boolean;
}

export type TimelineKind = "broker_event" | "chart_command" | "strategy_action" | "strategy_log" | "account_snapshot";

export interface ReplayTimelineItem {
  sequence: number;
  time_ns: number;
  kind: TimelineKind;
  payload: Record<string, unknown>;
}

export interface AccountSnapshot {
  run_id: string;
  timestamp_ns: number;
  sequence: number;
  currency: string;
  balance: string;
  equity: string;
  margin: string;
  free_margin: string;
  margin_level_percent: string | null;
  floating_pnl: string;
  peak_equity: string;
  drawdown_amount: string;
  drawdown_percent: string;
}

export interface OrderRecord {
  order_id: string;
  request: {
    client_order_id: string;
    symbol: string;
    side: "buy" | "sell";
    order_type: "market" | "limit" | "stop";
    volume_lots: string;
    created_time_ns: number;
    price_ticks?: number;
    stop_loss_ticks?: number;
    take_profit_ticks?: number;
    reduce_only: boolean;
    position_id?: string;
  };
  status: string;
  filled_volume_lots: string;
  average_fill_price_ticks: string | null;
  terminal_time_ns: number | null;
  rejection_reason: string | null;
}

export interface PositionRecord {
  position_id: string;
  symbol: string;
  side: "long" | "short";
  status: string;
  volume_lots: string;
  average_entry_price_ticks: string;
  opened_time_ns: number;
  current_price_ticks: number | null;
  stop_loss_ticks: number | null;
  take_profit_ticks: number | null;
  realized_pnl: string;
  unrealized_pnl: string;
}

export interface FillRecord {
  fill_id: string;
  order_id: string;
  symbol: string;
  side: "buy" | "sell";
  time_ns: number;
  price_ticks: number;
  volume_lots: string;
  commission: string;
  spread_cost: string;
  slippage_cost: string;
}

export interface TradeRecord {
  trade_id: string;
  position_id: string;
  symbol: string;
  side: "long" | "short";
  volume_lots: string;
  entry_time_ns: number;
  exit_time_ns: number;
  entry_price_ticks: string;
  exit_price_ticks: string;
  stop_loss_ticks: number | null;
  take_profit_ticks: number | null;
  gross_pnl: string;
  commission: string;
  spread_cost: string;
  slippage_cost: string;
  swap: string;
  net_pnl: string;
  initial_risk: string | null;
  realized_r_multiple: string | null;
  mae: string;
  mfe: string;
  intrabar_ambiguous: boolean;
  exit_reason: string;
}

export interface ReplayBootstrap {
  run: ReplayRunDescriptor;
  symbol: string;
  timeframe: Timeframe;
  cursor_sequence: number;
  cursor_time_ns: number;
  progress: string;
  price_digits: number;
  price_tick_size: string;
  bars: ReplayBar[];
  timeline: ReplayTimelineItem[];
  account: AccountSnapshot;
  orders: OrderRecord[];
  positions: PositionRecord[];
  fills: FillRecord[];
  trades: TradeRecord[];
  strategy_report: Record<string, unknown>;
  broker_report: Record<string, unknown>;
}

export interface ReplayFrame {
  frame_type: "advance" | "reset" | "state" | "completed";
  cursor_sequence: number;
  cursor_time_ns: number;
  progress: string;
  playing: boolean;
  speed: string;
  bars: ReplayBar[];
  timeline: ReplayTimelineItem[];
  account: AccountSnapshot | null;
}

export type SocketMessage =
  | { type: "bootstrap"; data: ReplayBootstrap }
  | { type: "frame"; data: ReplayFrame }
  | { type: "resync_required"; detail: string; dropped_messages: number }
  | { type: "error"; detail: string };

export interface ReplayControlCommand {
  action: "play" | "pause" | "step_forward" | "step_backward" | "seek_time" | "seek_progress" | "set_speed" | "set_timeframe" | "reset";
  value?: string | number;
}

export interface EquityCurvePoint {
  time_ns: number;
  balance: string;
  equity: string;
  floating_pnl: string;
  margin: string;
  drawdown_amount: string;
  drawdown_percent: string;
}

export interface PeriodReturnPoint {
  time_ns: number;
  period: string;
  equity: string;
  pnl: string;
  return_percent: string;
}

export interface RollingMetricPoint {
  time_ns: number;
  sharpe_ratio: string | null;
  sortino_ratio: string | null;
  annualized_volatility_percent: string | null;
  rolling_drawdown_percent: string;
}

export interface PerformanceMetrics {
  initial_balance: string;
  final_balance: string;
  final_equity: string;
  gross_profit: string;
  gross_loss: string;
  gross_pnl: string;
  net_pnl: string;
  total_return_percent: string;
  cagr_percent: string | null;
  profit_factor: string | null;
  expectancy: string;
  average_trade: string;
  median_trade: string;
  average_win: string | null;
  average_loss: string | null;
  payoff_ratio: string | null;
  best_trade: string | null;
  worst_trade: string | null;
  average_r_multiple: string | null;
  median_r_multiple: string | null;
  system_quality_number: string | null;
}

export interface RiskMetrics {
  max_drawdown_amount: string;
  max_drawdown_percent: string;
  max_drawdown_duration_minutes: string;
  max_recovery_duration_minutes: string | null;
  average_drawdown_percent: string;
  annualized_volatility_percent: string | null;
  sharpe_ratio: string | null;
  sortino_ratio: string | null;
  calmar_ratio: string | null;
  recovery_factor: string | null;
  ulcer_index: string;
  value_at_risk_percent: string | null;
  conditional_value_at_risk_percent: string | null;
  best_day_return_percent: string | null;
  worst_day_return_percent: string | null;
}

export interface TradeBehaviorMetrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  long_trades: number;
  short_trades: number;
  win_rate_percent: string;
  loss_rate_percent: string;
  average_holding_minutes: string;
  median_holding_minutes: string;
  longest_holding_minutes: string;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  time_in_market_percent: string;
  ambiguous_trade_count: number;
  average_mae: string;
  average_mfe: string;
  average_mfe_capture_percent: string | null;
}

export interface ExecutionCostMetrics {
  commission: string;
  spread_cost: string;
  slippage_cost: string;
  swap: string;
  total_cost: string;
  average_cost_per_trade: string;
  cost_to_gross_profit_percent: string | null;
  commission_share_percent: string;
  spread_share_percent: string;
  slippage_share_percent: string;
}

export interface PeriodicPerformance {
  period: string;
  start_time_ns: number;
  end_time_ns: number;
  opening_equity: string;
  closing_equity: string;
  net_pnl: string;
  return_percent: string;
  max_drawdown_percent: string;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_percent: string;
}

export interface BreakdownRow {
  key: string;
  label: string;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_percent: string;
  net_pnl: string;
  average_pnl: string;
  profit_factor: string | null;
  average_r_multiple: string | null;
  average_holding_minutes: string;
}

export interface DistributionBucket {
  label: string;
  lower_bound: string;
  upper_bound: string;
  count: number;
  percentage: string;
}

export interface DrawdownEpisode {
  start_time_ns: number;
  trough_time_ns: number;
  recovery_time_ns: number | null;
  max_drawdown_amount: string;
  max_drawdown_percent: string;
  duration_minutes: string;
  recovery_minutes: string | null;
}

export interface AnalyticsReport {
  schema_version: string;
  report_id: string;
  run_id: string;
  generated_at: string;
  start_time_ns: number;
  end_time_ns: number;
  currency: string;
  performance: PerformanceMetrics;
  risk: RiskMetrics;
  trades: TradeBehaviorMetrics;
  costs: ExecutionCostMetrics;
  equity_curve: EquityCurvePoint[];
  daily_returns: PeriodReturnPoint[];
  rolling_metrics: RollingMetricPoint[];
  monthly_performance: PeriodicPerformance[];
  yearly_performance: PeriodicPerformance[];
  drawdown_episodes: DrawdownEpisode[];
  side_breakdown: BreakdownRow[];
  symbol_breakdown: BreakdownRow[];
  exit_reason_breakdown: BreakdownRow[];
  weekday_breakdown: BreakdownRow[];
  hour_breakdown: BreakdownRow[];
  pnl_distribution: DistributionBucket[];
  r_multiple_distribution: DistributionBucket[];
  duration_distribution: DistributionBucket[];
}

export interface AnalyticsComparisonRow {
  run_id: string;
  name: string;
  net_pnl: string;
  total_return_percent: string;
  max_drawdown_percent: string;
  sharpe_ratio: string | null;
  sortino_ratio: string | null;
  profit_factor: string | null;
  win_rate_percent: string;
  total_trades: number;
}

export interface AnalyticsComparisonReport {
  rows: AnalyticsComparisonRow[];
  sort_by: "net_pnl" | "total_return_percent" | "max_drawdown_percent" | "sharpe_ratio" | "profit_factor";
}

export interface StrategyPackageSummary {
  package_id: string;
  strategy_id: string;
  name: string;
  version: string;
  description: string;
  entrypoint: string;
  package_path: string;
  tags: string[];
  enabled: boolean;
}

export interface LiveRunState {
  run_id: string;
  strategy_package_id: string;
  status: "created" | "starting" | "paused" | "running" | "rewinding" | "finalizing" | "completed" | "failed" | "cancelled";
  playing: boolean;
  speed_bars_per_second: string;
  visualization_mode: "replay" | "turbo";
  processed_close_batches: number;
  processed_execution_bars: number;
  current_time_ns: number;
  progress: string;
  max_close_batches: number | null;
  error: string | null;
  replay_ready: boolean;
  created_at: string;
  updated_at: string;
  descriptor: ReplayRunDescriptor;
}

export interface EngineCatalog {
  strategies: StrategyPackageSummary[];
  runs: LiveRunState[];
}

export interface LiveRunCreateRequest {
  strategy_package_id: string;
  run_id?: string;
  name?: string;
  parameters?: Record<string, unknown>;
  max_close_batches?: number;
  start_paused?: boolean;
  speed_bars_per_second?: number;
  visualization_mode?: "auto" | "replay" | "turbo";
  ui_snapshot_interval_ms?: number;
  ui_window_bars?: number;
  ui_timeline_limit?: number;
}
