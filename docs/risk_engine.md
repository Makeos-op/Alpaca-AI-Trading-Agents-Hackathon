# Deterministic RiskEngine Guardrail & Mathematical Specification

## Overview

The `RiskEngine` (`src/risk/risk_engine.py` & `src/risk/models.py`) fulfills Hackathon Requirement R2 by acting as an infrangible, deterministic pre-trade validation gate. It eliminates LLM hallucinations, sizing overruns, crossed-market execution, and illiquidity risks.

---

## 1. Mathematical Formulations & Guardrails

All mathematical operations use `decimal.Decimal` with rounding mode `ROUND_HALF_UP` to prevent floating-point representation drift.

### 1.1 Trade Cost
$$C_{\text{trade}} = P_{\text{effective}} \times 100 \times Q$$
Where:
- $P_{\text{effective}} = \max(P_{\text{ask}}, P_{\text{limit}})$ (or $P_{\text{ask}}$ if market order).
- $Q$ is the proposed number of option contracts ($Q \ge 1$).

### 1.2 5% Single-Trade Risk Limit
$$L_{\text{single\_risk}} = \text{quantize}(V_{\text{portfolio}} \times 0.05, 0.01)$$
The proposed trade is rejected if:
$$C_{\text{trade}} > L_{\text{single\_risk}}$$
Reason code: `RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`.

### 1.3 Effective Buying Power & Cash Clamping
$$B_{\text{effective}} = \max(0.00, \min(L_{\text{single\_risk}}, BP, C_{\text{cash}}))$$
If $C_{\text{trade}} > B_{\text{effective}}$, the order is rejected with:
`RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER`.

### 1.4 Cumulative 25% Options Portfolio Cap
$$X_{\text{projected}} = X_{\text{current}} + C_{\text{trade}} \le \text{quantize}(V_{\text{portfolio}} \times 0.25, 0.01)$$
Where $X_{\text{current}}$ is the account's existing option exposure.
Exceeding this threshold triggers `RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP`.

### 1.5 Recommended Safe Sizing Calculator
When an oversized trade proposal is submitted, `RiskEngine` calculates the maximum safe quantity:
$$Q_{\text{max\_safe}} = \left\lfloor \frac{\min(B_{\text{effective}}, B_{\text{remaining\_options\_cap}})}{P_{\text{ask}} \times 100} \right\rfloor$$
This safe sizing is returned in `verdict.max_safe_quantity` and `verdict.recommended_quantity`.

---

## 2. Market Microstructure & Liquidity Guardrails

| Metric | Guardrail Condition | Rejection Reason Code |
|---|---|---|
| **Crossed / Zero Quote** | $P_{\text{bid}} \le 0$, $P_{\text{ask}} \le 0$, or $P_{\text{bid}} \ge P_{\text{ask}}$ | `ERR_CROSSED_OR_ZERO_QUOTE` |
| **Option Relative Spread** | $(P_{\text{ask}} - P_{\text{bid}}) / P_{\text{mid}} > 0.0500$ (5.00%) | `ERR_WIDE_BID_ASK_SPREAD` |
| **Option Absolute Spread** | $P_{\text{ask}} - P_{\text{bid}} > \$0.50$ | `ERR_WIDE_BID_ASK_SPREAD` |
| **Underlying Equity Spread** | $(P_{\text{underlying\_ask}} - P_{\text{underlying\_bid}}) / P_{\text{underlying\_mid}} > 0.0100$ | `ERR_UNDERLYING_SPREAD_EXCEEDS_MAX` |
| **Open Interest Floor** | $\text{OI} < 500$ contracts | `ERR_INSUFFICIENT_OPEN_INTEREST` |
| **Volume Floor** | $\text{Volume} < 100$ contracts | `ERR_INSUFFICIENT_VOLUME` |

---

## 3. Greeks & Expiration Horizon Guardrails

| Metric | Guardrail Condition | Rejection Reason Code |
|---|---|---|
| **Expiration Horizon (DTE)** | $\text{DTE} < 1$ (0-DTE pin risk) or $\text{DTE} > 30$ | `ERR_DTE_OUT_OF_BOUNDS` |
| **Call Delta ($\Delta_{\text{call}}$)** | $\Delta_{\text{call}} < 0.30$ or $\Delta_{\text{call}} > 0.70$ | `ERR_DELTA_OUT_OF_BOUNDS` |
| **Put Delta ($\Delta_{\text{put}}$)** | $\Delta_{\text{put}} < -0.70$ or $\Delta_{\text{put}} > -0.30$ | `ERR_DELTA_OUT_OF_BOUNDS` |
| **Daily Theta Decay Rate** | $|\Theta| / P_{\text{ask}} > 0.0500$ (5.00% daily loss) | `ERR_THETA_DECAY_EXCESSIVE` |
| **Absolute Daily Theta Cap** | $|\Theta| > \$0.15$ ($15.00/contract/day) | `ERR_THETA_DECAY_EXCESSIVE` |
| **Implied Volatility (IV)** | $\text{IV} < 0.05$ (5%) or $\text{IV} > 1.00$ (100%) | `ERR_IV_OUT_OF_BOUNDS` |

---

## 4. Account Health Invariants

Before individual trade parameters are examined, account-level checks are performed:
- `is_frozen == True` → `ERR_ACCOUNT_FROZEN_OR_RESTRICTED`
- `is_active == False` → `ERR_ACCOUNT_FROZEN_OR_RESTRICTED`
- Margin call condition ($V_{\text{portfolio}} < \text{maintenance\_margin}$) → `ERR_ACCOUNT_FROZEN_OR_RESTRICTED`
- Zero or negative portfolio value ($V_{\text{portfolio}} \le 0$) → `ERR_ACCOUNT_FROZEN_OR_RESTRICTED`
