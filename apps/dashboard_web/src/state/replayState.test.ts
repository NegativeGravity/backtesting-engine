import { describe, expect, it } from "vitest";
import type { OrderRecord, ReplayBar, ReplayBootstrap, ReplayFrame } from "../lib/types";
import { initialReplayState, replayReducer } from "./replayState";

const bootstrap = {
  run: {
    run_id: "run_test",
    name: "Test",
    strategy_id: "strategy",
    strategy_instance_id: "strategy_primary",
    dataset_id: "dataset",
    default_symbol: "XAUUSD",
    default_timeframe: "M1",
    execution_timeframe: "M1",
    available_symbols: ["XAUUSD"],
    available_timeframes: ["M1"],
    start_time_ns: 1,
    end_time_ns: 10,
    metrics: {
      initial_balance: "100000",
      final_balance: "100010",
      final_equity: "100010",
      gross_pnl: "10",
      net_pnl: "10",
      commission: "0",
      spread_cost: "0",
      slippage_cost: "0",
      swap: "0",
      total_trades: 1,
      winning_trades: 1,
      losing_trades: 0,
      long_trades: 1,
      short_trades: 0,
      win_rate: "100",
      profit_factor: null,
      average_r_multiple: "1",
      max_drawdown_amount: "0",
      max_drawdown_percent: "0"
    }
  },
  symbol: "XAUUSD",
  timeframe: "M1",
  cursor_sequence: 1,
  cursor_time_ns: 2,
  progress: "0.1",
  price_digits: 2,
  price_tick_size: "0.01",
  bars: [],
  timeline: [],
  account: {
    run_id: "run_test",
    timestamp_ns: 2,
    sequence: 1,
    currency: "USD",
    balance: "100000",
    equity: "100000",
    margin: "0",
    free_margin: "100000",
    margin_level_percent: null,
    floating_pnl: "0",
    peak_equity: "100000",
    drawdown_amount: "0",
    drawdown_percent: "0"
  },
  orders: [],
  positions: [],
  fills: [],
  trades: [],
  strategy_report: {},
  broker_report: {}
} satisfies ReplayBootstrap;


function bar(sequence: number): ReplayBar {
  return {
    symbol: "XAUUSD",
    timeframe: "M1",
    sequence,
    open_time_ns: sequence * 60_000_000_000,
    close_time_ns: (sequence + 1) * 60_000_000_000,
    open: "2500",
    high: "2501",
    low: "2499",
    close: "2500.5",
    tick_volume: 1,
    real_volume: "0",
    source_spread_points: 7,
    is_complete: true
  };
}

describe("replayReducer", () => {
  it("replaces replay state on bootstrap", () => {
    const state = replayReducer(initialReplayState, { type: "bootstrap_received", bootstrap });
    expect(state.bootstrap?.run.run_id).toBe("run_test");
    expect(state.account?.balance).toBe("100000");
  });

  it("appends incremental frame data", () => {
    const initial = replayReducer(initialReplayState, { type: "bootstrap_received", bootstrap });
    const frame = {
      frame_type: "advance",
      cursor_sequence: 2,
      cursor_time_ns: 3,
      progress: "0.2",
      playing: true,
      speed: "10",
      bars: [],
      timeline: [{ sequence: 1, time_ns: 3, kind: "strategy_log", payload: { message: "ok" } }],
      account: null
    } satisfies ReplayFrame;
    const state = replayReducer(initial, { type: "frame_received", frame });
    expect(state.bootstrap?.cursor_sequence).toBe(2);
    expect(state.timeline).toHaveLength(1);
  });



  it("keeps the order request when an order-filled event carries a fill payload", () => {
    const activeOrder = {
      order_id: "ord-1",
      request: {
        client_order_id: "client-1",
        symbol: "XAUUSD",
        side: "buy",
        order_type: "market",
        volume_lots: "0.10",
        created_time_ns: 100,
        reduce_only: false
      },
      status: "active",
      filled_volume_lots: "0",
      average_fill_price_ticks: null,
      terminal_time_ns: null,
      rejection_reason: null
    } satisfies OrderRecord;
    const initial = replayReducer(initialReplayState, {
      type: "bootstrap_received",
      bootstrap: { ...bootstrap, orders: [activeOrder] }
    });
    const frame = {
      frame_type: "advance",
      cursor_sequence: 2,
      cursor_time_ns: 200,
      progress: "0.2",
      playing: true,
      speed: "10",
      bars: [],
      timeline: [{
        sequence: 10,
        time_ns: 200,
        kind: "broker_event",
        payload: {
          event_type: "order.filled",
          payload: {
            fill_id: "fill-1",
            order_id: "ord-1",
            run_id: "run_test",
            symbol: "XAUUSD",
            side: "buy",
            time_ns: 200,
            price_ticks: 250123,
            volume_lots: "0.10",
            commission: "0.35",
            spread_cost: "0.70",
            slippage_cost: "0",
            fill_reason: "market_open"
          }
        }
      }],
      account: null
    } satisfies ReplayFrame;

    const state = replayReducer(initial, { type: "frame_received", frame });

    expect(state.orders).toHaveLength(1);
    expect(state.orders[0]?.request.client_order_id).toBe("client-1");
    expect(state.orders[0]?.status).toBe("filled");
    expect(state.orders[0]?.average_fill_price_ticks).toBe("250123");
    expect(state.orders[0]?.terminal_time_ns).toBe(200);
  });

  it("ignores a standalone fill payload instead of inserting a malformed order", () => {
    const initial = replayReducer(initialReplayState, {
      type: "bootstrap_received",
      bootstrap
    });
    const frame = {
      frame_type: "advance",
      cursor_sequence: 2,
      cursor_time_ns: 200,
      progress: "0.2",
      playing: true,
      speed: "10",
      bars: [],
      timeline: [{
        sequence: 10,
        time_ns: 200,
        kind: "broker_event",
        payload: {
          event_type: "order.filled",
          payload: {
            order_id: "ord-missing",
            time_ns: 200,
            price_ticks: 250123,
            volume_lots: "0.10"
          }
        }
      }],
      account: null
    } satisfies ReplayFrame;

    const state = replayReducer(initial, { type: "frame_received", frame });

    expect(state.orders).toHaveLength(0);
  });

  it("bounds retained bootstrap collections for long-running dashboards", () => {
    const oversized: ReplayBootstrap = {
      ...bootstrap,
      timeline: Array.from({ length: 5_100 }, (_, index) => ({
        sequence: index + 1,
        time_ns: index + 1,
        kind: "strategy_log",
        payload: { message: "bounded" }
      })),
      fills: Array.from({ length: 5_100 }, (_, index) => ({
        fill_id: `fill-${index}`,
        order_id: `order-${index}`,
        symbol: "XAUUSD",
        side: "buy",
        time_ns: index + 1,
        price_ticks: 250000,
        volume_lots: "0.10",
        commission: "0",
        spread_cost: "0",
        slippage_cost: "0"
      }))
    };
    const state = replayReducer(initialReplayState, {
      type: "bootstrap_received",
      bootstrap: oversized
    });
    expect(state.timeline).toHaveLength(1_500);
    expect(state.bootstrap?.timeline).toHaveLength(1_500);
    expect(state.bootstrap?.fills).toHaveLength(1_500);
  });

  it("keeps chart buffers stable while UI state advances", () => {
    const fullBootstrap: ReplayBootstrap = {
      ...bootstrap,
      bars: Array.from({ length: 12_000 }, (_, index) => bar(index + 1))
    };
    const initial = replayReducer(initialReplayState, {
      type: "bootstrap_received",
      bootstrap: fullBootstrap
    });
    const initialBars = initial.bootstrap?.bars;
    const frame = {
      frame_type: "advance",
      cursor_sequence: 12_001,
      cursor_time_ns: 12_001,
      progress: "0.5",
      playing: true,
      speed: "100",
      bars: [bar(12_001)],
      timeline: [],
      account: null
    } satisfies ReplayFrame;
    const state = replayReducer(initial, { type: "frame_received", frame });
    expect(state.bootstrap?.bars).toBe(initialBars);
    expect(state.bootstrap?.cursor_sequence).toBe(12_001);
  });

});

it("replaces an overlapping tail without duplicating bars", async () => {
  const { mergeVisibleBars } = await import("./replayState");
  const result = mergeVisibleBars(
    [bar(1), bar(2), bar(3), bar(4)],
    [bar(3), bar(4), bar(5)]
  );
  expect(result.map(item => item.sequence)).toEqual([1, 2, 3, 4, 5]);
});

it("refreshes live orders and positions from account snapshot events", () => {
  const initial = replayReducer(initialReplayState, {
    type: "bootstrap_received",
    bootstrap
  });
  const position = {
    position_id: "position-1",
    symbol: "XAUUSD",
    side: "long",
    status: "open",
    volume_lots: "0.10",
    average_entry_price_ticks: "250000",
    opened_time_ns: 100,
    current_price_ticks: 250125,
    stop_loss_ticks: 249900,
    take_profit_ticks: 250300,
    realized_pnl: "0",
    unrealized_pnl: "12.5"
  } as const;
  const frame = {
    frame_type: "advance",
    cursor_sequence: 3,
    cursor_time_ns: 300,
    progress: "0.3",
    playing: true,
    speed: "100",
    bars: [],
    timeline: [{
      sequence: 11,
      time_ns: 300,
      kind: "broker_event",
      payload: {
        event_type: "account.updated",
        payload: {
          orders: [],
          positions: [position]
        }
      }
    }],
    account: null
  } satisfies ReplayFrame;

  const state = replayReducer(initial, { type: "frame_received", frame });

  expect(state.positions).toHaveLength(1);
  expect(state.positions[0]?.current_price_ticks).toBe(250125);
  expect(state.positions[0]?.unrealized_pnl).toBe("12.5");
});

it("preserves broker collection references for identical account snapshots", () => {
  const initial = replayReducer(initialReplayState, {
    type: "bootstrap_received",
    bootstrap
  });
  const frame = {
    frame_type: "advance",
    cursor_sequence: 2,
    cursor_time_ns: 2,
    progress: "0.2",
    playing: true,
    speed: "100",
    bars: [],
    timeline: [{
      sequence: 20,
      time_ns: 2,
      kind: "broker_event",
      payload: {
        event_type: "account.updated",
        payload: { orders: [], positions: [] }
      }
    }],
    account: null
  } satisfies ReplayFrame;

  const next = replayReducer(initial, { type: "frame_received", frame });

  expect(next.orders).toBe(initial.orders);
  expect(next.positions).toBe(initial.positions);
  expect(next.trades).toBe(initial.trades);
});
