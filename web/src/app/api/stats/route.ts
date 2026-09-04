import { NextResponse } from "next/server";
import { getLiveTrades } from "@/lib/tradeLogParser";
import { DashboardStats } from "@/types/trade";

export const dynamic = "force-dynamic";

export async function GET() {
  const { trades } = getLiveTrades();
  const totalTrades = trades.length;
  const executedCount = trades.filter((t) => t.execution_status === "FILLED").length;
  const rejectedCount = trades.filter((t) => t.execution_status === "REJECTED" || t.execution_status === "ERROR").length;
  const simulatedCount = trades.filter((t) => t.execution_status === "SIMULATED").length;

  const approvalRate = totalTrades > 0 ? (executedCount / totalTrades) * 100 : 0;

  const totalCommittedCost = trades
    .filter((t) => t.execution_status === "FILLED")
    .reduce((acc, t) => {
      const cost = parseFloat(t.trade_cost || "0");
      return acc + (isNaN(cost) ? 0 : cost);
    }, 0);

  const avgRiskPctUsed =
    totalTrades > 0
      ? trades.reduce((acc, t) => {
          const pct = parseFloat(t.portfolio_risk_pct_used || "0");
          return acc + (isNaN(pct) ? 0 : pct);
        }, 0) / totalTrades
      : 0;

  const tickerCounts: Record<string, number> = {};
  trades.forEach((t) => {
    tickerCounts[t.ticker] = (tickerCounts[t.ticker] || 0) + 1;
  });

  const uniqueTickers = Object.keys(tickerCounts);
  let mostTradedTicker = "N/A";
  let maxTrades = 0;
  for (const [tick, cnt] of Object.entries(tickerCounts)) {
    if (cnt > maxTrades) {
      maxTrades = cnt;
      mostTradedTicker = tick;
    }
  }

  const rejectionMap: Record<string, number> = {};
  trades.filter((t) => !t.is_approved || t.execution_status === "ERROR").forEach((t) => {
    t.risk_reasons.forEach((r) => {
      const simplified = r.includes("Spread")
        ? "Spread Bid/Ask Excesivo (> 5%)"
        : r.includes("DTE")
        ? "Horizonte DTE Inválido (0-DTE pin risk)"
        : r.includes("límite máximo") || r.includes("5%")
        ? "Supera Límite de Riesgo (5% Portafolio)"
        : r.includes("not found") || r.includes("422")
        ? "Contrato no encontrado en Broker (422)"
        : r;
      rejectionMap[simplified] = (rejectionMap[simplified] || 0) + 1;
    });
  });

  const rejectionReasonsSummary = Object.entries(rejectionMap).map(([reason, count]) => ({
    reason,
    count,
  }));

  const stats: DashboardStats = {
    totalTrades,
    executedCount,
    rejectedCount,
    simulatedCount,
    approvalRate: parseFloat(approvalRate.toFixed(2)),
    totalCommittedCost: parseFloat(totalCommittedCost.toFixed(2)),
    avgRiskPctUsed: parseFloat((avgRiskPctUsed * 100).toFixed(3)),
    uniqueTickers,
    mostTradedTicker,
    rejectionReasonsSummary,
  };

  return NextResponse.json(stats);
}
