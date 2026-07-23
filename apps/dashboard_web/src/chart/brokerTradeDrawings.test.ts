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

  it("normalizes broker exit reasons", () => {
    expect(normalizeExitKind("stop_loss")).toBe("stop_loss");
    expect(normalizeExitKind("TP")).toBe("take_profit");
    expect(normalizeExitKind("margin stop out")).toBe("liquidation");
    expect(normalizeExitKind("strategy_close")).toBe("manual");
  });
});
