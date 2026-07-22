import { describe, expect, it } from "vitest";
import { buildBrokerTradeDrawings, normalizeExitKind } from "./brokerTradeDrawings";

const trade = {
  trade_id: "trade-1",
  position_id: "position-1",
  symbol: "XAUUSD",
  side: "long" as const,
  volume_lots: "1",
  entry_time_ns: 1_000_000_000,
  exit_time_ns: 2_000_000_000,
  entry_price_ticks: "250000",
  exit_price_ticks: "251000",
  stop_loss_ticks: 249000,
  take_profit_ticks: 251000,
  gross_pnl: "100",
  commission: "1",
  spread_cost: "2",
  slippage_cost: "0",
  swap: "0",
  net_pnl: "97",
  initial_risk: "100",
  realized_r_multiple: "0.97",
  mae: "10",
  mfe: "120",
  intrabar_ambiguous: false,
  exit_reason: "take_profit"
};

describe("broker trade drawings", () => {
  it("materializes a closed trade with explicit target outcome", () => {
    const drawings = buildBrokerTradeDrawings({
      symbol: "XAUUSD",
      trades: [trade],
      positions: [],
      latestTimeNs: trade.exit_time_ns
    });

    expect(drawings).toHaveLength(1);
    expect(drawings[0]?.payload.exit_kind).toBe("take_profit");
    expect(drawings[0]?.payload.entry_time_ns).toBe(trade.entry_time_ns);
    expect(drawings[0]?.payload.exit_time_ns).toBe(trade.exit_time_ns);
  });


  it("keeps overlapping positions isolated by chain and position id", () => {
    const positions = [
      {
        position_id: "position-day-a",
        symbol: "XAUUSD",
        side: "long" as const,
        status: "open",
        volume_lots: "1",
        average_entry_price_ticks: "2939360",
        opened_time_ns: 3_000_000_000,
        entry_tags: { chain_id: "2025-02-24-0001", trade_date: "2025-02-24", leg: "1" },
        current_price_ticks: 2925000,
        stop_loss_ticks: 2921300,
        take_profit_ticks: 2966450,
        realized_pnl: "0",
        unrealized_pnl: "0"
      },
      {
        position_id: "position-day-b",
        symbol: "XAUUSD",
        side: "short" as const,
        status: "open",
        volume_lots: "1",
        average_entry_price_ticks: "2905800",
        opened_time_ns: 4_000_000_000,
        entry_tags: { chain_id: "2025-02-25-0002", trade_date: "2025-02-25", leg: "1" },
        current_price_ticks: 2900000,
        stop_loss_ticks: 2930140,
        take_profit_ticks: 2869290,
        realized_pnl: "0",
        unrealized_pnl: "0"
      }
    ];

    const drawings = buildBrokerTradeDrawings({
      symbol: "XAUUSD",
      trades: [],
      positions,
      latestTimeNs: 5_000_000_000
    });

    expect(drawings).toHaveLength(2);
    const byPosition = new Map(drawings.map(drawing => [drawing.payload.position_id, drawing]));
    expect(byPosition.get("position-day-a")?.payload.stop_loss_ticks).toBe(2921300);
    expect(byPosition.get("position-day-a")?.payload.chain_id).toBe("2025-02-24-0001");
    expect(byPosition.get("position-day-b")?.payload.stop_loss_ticks).toBe(2930140);
    expect(byPosition.get("position-day-b")?.payload.chain_id).toBe("2025-02-25-0002");
  });

  it("normalizes broker exit reasons", () => {
    expect(normalizeExitKind("stop_loss")).toBe("stop_loss");
    expect(normalizeExitKind("TP")).toBe("take_profit");
    expect(normalizeExitKind("margin stop out")).toBe("liquidation");
    expect(normalizeExitKind("strategy_close")).toBe("manual");
  });
});
