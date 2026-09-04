export type ExecutionStatus = "FILLED" | "REJECTED" | "SIMULATED" | "PENDING" | "ERROR";
export type AssetClass = "equity" | "option" | "stock";
export type OptionType = "CALL" | "PUT" | "EQUITY";

export interface Greeks {
  delta?: string | number;
  gamma?: string | number;
  theta?: string | number;
  vega?: string | number;
  implied_volatility?: string | number;
}

export interface MarketDataSnapshot {
  ticker: string;
  underlying_symbol: string;
  underlying_price: string;
  option_symbol?: string;
  bid: string;
  ask: string;
  mid_price: string;
  spread_pct: string;
  volume: number;
  open_interest: number;
  delta?: string;
  theta?: string;
  dte?: number;
  greeks?: Greeks;
}

export interface AgentProposal {
  strategy_name: string;
  signal_type: string;
  confidence: string;
  target_contract_symbol: string;
  target_option_type: string;
  action: "BUY" | "SELL";
  quantity: number;
  symbol: string;
  side: "buy" | "sell";
  rationale: string;
}

export interface RiskVerdict {
  is_approved: boolean;
  reason_code: string;
  message: string;
  trade_cost: string;
  max_allowed_budget: string;
  portfolio_risk_pct_used: string;
  reasons: string[];
  reason_codes: string[];
  warnings?: string[];
  audited_metrics?: {
    portfolio_value?: string;
    buying_power?: string;
    cash?: string;
    trade_cost?: string;
    max_allowed_risk?: string;
    max_allowed_budget?: string;
    effective_budget?: string;
    portfolio_risk_pct?: string;
    spread_pct?: string;
    dte?: number;
    volume?: number;
    open_interest?: number;
    delta?: string;
    theta?: string;
    recommended_quantity?: number;
    max_safe_quantity?: number;
  };
}

export interface ExecutionResult {
  executed: boolean;
  execution_status: ExecutionStatus;
  order_id: string | null;
  status: string;
  filled_qty: number;
  filled_avg_price: string | null;
}

export interface TradeRecord {
  id: string;
  timestamp: string;
  event_type: "TRADE_EXECUTED" | "TRADE_REJECTED" | "TRADE_SIMULATED";
  mode: string;
  ticker: string;
  option_symbol: string;
  contract_type: OptionType;
  strike_price: string;
  expiration_date: string;
  dte: number;
  quantity: number;
  trade_cost: string;
  strategy_name: string;
  action: "BUY" | "SELL";
  is_approved: boolean;
  risk_reasons: string[];
  risk_warnings?: string[];
  portfolio_risk_pct_used: string;
  order_id: string | null;
  execution_status: ExecutionStatus;
  fill_price: string | null;
  asset_class: AssetClass;
  greeks?: Greeks;
  agent_proposal: AgentProposal;
  risk_verdict: RiskVerdict;
  market_data_snapshot: MarketDataSnapshot;
  execution_result: ExecutionResult;
}

export interface AccountInfo {
  account_id: string;
  status: string;
  cash: string;
  portfolio_value: string;
  buying_power: string;
  equity: string;
  daytrading_buying_power: string;
  daytrading_count: number;
  is_daytrader: boolean;
  is_active: boolean;
  currency: string;
}

export interface DashboardStats {
  totalTrades: number;
  executedCount: number;
  rejectedCount: number;
  simulatedCount: number;
  approvalRate: number;
  totalCommittedCost: number;
  avgRiskPctUsed: number;
  uniqueTickers: string[];
  mostTradedTicker: string;
  rejectionReasonsSummary: { reason: string; count: number }[];
}

export interface ApiEndpointItem {
  name: string;
  method: "GET" | "POST";
  path: string;
  category: "Alpaca Paper Trading" | "Autonomous Agent API";
  description: string;
  status: "available" | "active" | "live_ready";
}

