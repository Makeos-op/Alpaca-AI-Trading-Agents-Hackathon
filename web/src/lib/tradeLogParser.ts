import fs from "fs";
import path from "path";
import { TradeRecord, OptionType, ExecutionStatus, AssetClass } from "@/types/trade";
import { HISTORICAL_TRADES } from "@/data/historicalTrades";

export function getLiveTrades(): { trades: TradeRecord[]; source: string } {
  const possiblePaths = [
    path.resolve(process.cwd(), "logs/trades.jsonl"),
    path.resolve(process.cwd(), "../logs/trades.jsonl"),
    "/workspaces/Alpaca-AI-Trading-Agents-Hackathon/logs/trades.jsonl",
  ];

  for (const logPath of possiblePaths) {
    if (fs.existsSync(logPath)) {
      try {
        const fileContent = fs.readFileSync(logPath, "utf-8");
        const lines = fileContent.split("\n").filter((l) => l.trim().length > 0);
        if (lines.length === 0) continue;

        const records: TradeRecord[] = lines.map((line, idx) => {
          const raw = JSON.parse(line);
          const contractType = (raw.contract_type || (raw.asset_class === "equity" ? "EQUITY" : "CALL")) as OptionType;
          const executionStatus = (raw.execution_status || (raw.event_type === "TRADE_EXECUTED" ? "FILLED" : "REJECTED")) as ExecutionStatus;
          const assetClass = (raw.asset_class || (contractType === "EQUITY" ? "equity" : "option")) as AssetClass;

          return {
            id: `trade-${String(idx + 1).padStart(5, "0")}`,
            timestamp: raw.timestamp || new Date().toISOString(),
            event_type: raw.event_type || (executionStatus === "FILLED" ? "TRADE_EXECUTED" : "TRADE_REJECTED"),
            mode: raw.mode || "scan",
            ticker: raw.ticker || raw.market_data_snapshot?.ticker || "N/A",
            option_symbol: raw.option_symbol || raw.symbol || raw.ticker || "N/A",
            contract_type: contractType,
            strike_price: String(raw.strike_price ?? "N/A"),
            expiration_date: raw.expiration_date || "N/A",
            dte: raw.dte ?? 0,
            quantity: raw.quantity ?? 1,
            trade_cost: String(raw.trade_cost || "0.00"),
            strategy_name: raw.strategy_name || raw.agent_proposal?.strategy_name || "AutonomousTrader",
            action: raw.action || raw.agent_proposal?.action || "BUY",
            is_approved: raw.is_approved ?? (executionStatus === "FILLED"),
            risk_reasons: raw.risk_reasons || raw.risk_verdict?.reasons || [],
            risk_warnings: raw.risk_warnings || raw.risk_verdict?.warnings || [],
            portfolio_risk_pct_used: String(raw.portfolio_risk_pct_used || "0.0"),
            order_id: raw.order_id || raw.execution_result?.order_id || null,
            execution_status: executionStatus,
            fill_price: raw.fill_price ? String(raw.fill_price) : (raw.execution_result?.filled_avg_price ? String(raw.execution_result.filled_avg_price) : null),
            asset_class: assetClass,
            greeks: raw.greeks || {},
            agent_proposal: raw.agent_proposal || {
              strategy_name: raw.strategy_name || "AutonomousTrader",
              signal_type: "TRADE",
              confidence: "0.85",
              target_contract_symbol: raw.option_symbol || raw.ticker,
              target_option_type: contractType,
              action: raw.action || "BUY",
              quantity: raw.quantity ?? 1,
              symbol: raw.ticker,
              side: (raw.action || "BUY").toLowerCase() as "buy" | "sell",
              rationale: raw.strategy_name || "Audited Trade",
            },
            risk_verdict: raw.risk_verdict || {
              is_approved: raw.is_approved ?? (executionStatus === "FILLED"),
              reason_code: raw.is_approved ? "APPROVED" : "REJECTED",
              message: (raw.risk_reasons && raw.risk_reasons.length > 0)
                ? raw.risk_reasons.join("; ")
                : (executionStatus === "FILLED" ? "Trade aprobado y ejecutado" : "Trade rechazado"),
              trade_cost: String(raw.trade_cost || "0.00"),
              max_allowed_budget: "5000.00",
              portfolio_risk_pct_used: String(raw.portfolio_risk_pct_used || "0.0"),
              reasons: raw.risk_reasons || [],
              reason_codes: [],
            },
            market_data_snapshot: raw.market_data_snapshot || {
              ticker: raw.ticker || "N/A",
              underlying_symbol: raw.ticker || "N/A",
              underlying_price: String(raw.strike_price || "0.00"),
              bid: "0.00",
              ask: "0.00",
              mid_price: "0.00",
              spread_pct: "0.00",
              volume: 0,
              open_interest: 0,
            },
            execution_result: raw.execution_result || {
              executed: executionStatus === "FILLED",
              execution_status: executionStatus,
              order_id: raw.order_id || null,
              status: executionStatus.toLowerCase(),
              filled_qty: raw.quantity ?? 1,
              filled_avg_price: raw.fill_price ? String(raw.fill_price) : null,
            },
          };
        });

        return { trades: records.reverse(), source: "live_trades_jsonl" };
      } catch (e) {
        console.error("Error al leer logs/trades.jsonl:", e);
      }
    }
  }

  return { trades: HISTORICAL_TRADES, source: "static_fallback" };
}

