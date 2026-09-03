# Draft-07 Structured JSONL Audit Logging

## Overview

The `TradeLogger` (`src/execution/trade_logger.py`) implements an auditable, append-only JSONL logging mechanism fulfilling Hackathon Requirement R3. Every evaluation and execution cycle generates an immutable record conforming to the **JSON Schema Draft-07** specification.

Log records are written to:
```
logs/trades.jsonl
```

---

## 1. Top-Level Schema Specification

Each line in `logs/trades.jsonl` is a distinct, valid JSON object containing seven required top-level fields:

| Field | Type | Description | Allowed Values |
|---|---|---|---|
| `timestamp` | string | ISO-8601 UTC timestamp | Format: `YYYY-MM-DDTHH:MM:SS...` |
| `event_type` | string | Nature of the logged event | `"TRADE_EXECUTED"`, `"TRADE_REJECTED"`, `"TRADE_SIMULATED"` |
| `mode` | string | Operational execution mode | `"scan"`, `"dry-run"`, `"loop"` |
| `market_data_snapshot` | object | Quotes, liquidity and Greeks | See Section 2.1 |
| `agent_proposal` | object | Proposed trade parameters from AI | See Section 2.2 |
| `risk_verdict` | object | Deterministic RiskEngine evaluation | See Section 2.3 |
| `execution_result` | object | Broker order result or simulation | See Section 2.4 |

---

## 2. Nested Container Specifications

### 2.1 `market_data_snapshot`
Documents the state of the market at the moment of proposal generation:
- `ticker`: Underlying ticker symbol (e.g. `"SPY"`)
- `underlying_price`: Current price of underlying equity (Decimal string)
- `option_symbol`: OCC standardized contract symbol
- `bid_price`: Contract bid price (Decimal string)
- `ask_price`: Contract ask price (Decimal string)
- `mid_price`: Midpoint price $(P_{\text{bid}} + P_{\text{ask}}) / 2$
- `spread_pct`: Relative bid-ask spread
- `volume`: Contract daily trading volume
- `open_interest`: Open interest
- `greeks`: Object containing `delta`, `gamma`, `theta`, `vega`, `implied_volatility`

### 2.2 `agent_proposal`
Documents the strategy signal and trade configuration:
- `strategy_name`: Identifier of the issuing agent strategy
- `signal_type`: Signal category (e.g. `"BULLISH_CALL_MOMENTUM"`)
- `confidence`: Confidence score $(0.00 - 1.00)$
- `target_option_type`: `"CALL"` or `"PUT"`
- `action`: `"BUY"` or `"SELL"`
- `quantity`: Number of contracts ($\ge 1$)
- `symbol`: Target option symbol
- `rationale`: Descriptive rationale from the strategy model

### 2.3 `risk_verdict`
Audits the deterministic findings of the `RiskEngine`:
- `is_approved`: Boolean flag (`true` if all guardrails passed, `false` otherwise)
- `reason_code`: Canonical `RiskReasonCode` enumeration string
- `message`: Diagnostic description of the approval or rejection
- `trade_cost`: Calculated capital requirement for the trade
- `max_allowed_budget`: Single-trade risk limit or clamped budget
- `portfolio_risk_pct_used`: Effective percentage of portfolio equity at risk
- `reasons`: Array of human-readable violation descriptions
- `reason_codes`: Array of specific violation reason codes
- `audited_metrics`: Object containing audited values (`trade_cost`, `max_allowed_risk`, `portfolio_risk_pct`, `spread_pct`, `dte`)

### 2.4 `execution_result`
Records broker response or simulated fill:
- `executed`: Boolean indicating whether order execution completed
- `execution_status`: Status string (`"FILLED"`, `"NEW"`, `"REJECTED"`, `"SIMULATED"`, `"ERROR"`)
- `order_id`: Alpaca broker order ID or simulated ID (`dry-run-order-...`)
- `status`: Lowercase status string
- `filled_qty`: Executed quantity (0 if rejected)
- `filled_avg_price`: Execution price (Decimal string or `null`)

---

## 3. Backward Compatibility Support

In addition to the nested Draft-07 objects, `TradeLogEntry` retains direct top-level properties (`ticker`, `option_symbol`, `trade_cost`, `is_approved`, etc.) to ensure zero breakage for legacy downstream analytics and existing test assertions.
