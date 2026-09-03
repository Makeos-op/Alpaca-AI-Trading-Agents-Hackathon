# Alpaca AI Options Autonomous Trading Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Alpaca MCP](https://img.shields.io/badge/Alpaca%20MCP-alpaca--mcp--server-green.svg)](https://github.com/alpacahq/alpaca-mcp-server)
[![Risk Engine](https://img.shields.io/badge/Risk%20Engine-5%25%20Infrangible%20Gate-red.svg)](src/risk/risk_engine.py)
[![Audit Log](https://img.shields.io/badge/Audit%20Log-Draft--07%20JSONL-orange.svg)](logs/trades.jsonl)

Autonomous options trading system integrating official Alpaca MCP Server (`alpaca-mcp-server`, PyPI package alpacahq/alpaca-mcp-server) and Alpaca CLI via a deterministic pre-trade risk engine guardrail (5% portfolio rule) to eliminate hallucinated or hazardous trades.

---

## 1. System Architecture

```
[ Market Data & Account State ]
              │
              ▼
    [ AlpacaGateway ] (src/execution/mcp_gateway.py)
       ├── StdioMCPTransport (alpaca-mcp-server via stdio JSON-RPC 2.0, launched via uvx)
       ├── CLITransport (/usr/bin/alpaca --format json fallback)
       └── MockMCPTransport (offline deterministic testing & unit simulation)
              │
              ▼
    [ Strategy & Screening Agents ] (src/agent.py, src/data/market.py)
              │ (generates TradeProposal)
              ▼
    [ Deterministic RiskEngine Guardrail ] (src/risk/risk_engine.py)
       ├── 5% Portfolio Risk Rule & Effective Buying Power Budget
       ├── Absolute ($0.50) & Relative (5%) Spread Caps, Crossed Quote Detection
       ├── Liquidity Floors (Volume ≥ 100, Open Interest ≥ 500)
       ├── Greeks Horizons (Delta [0.30, 0.70], Theta decay ≤ 5%/day, DTE 1-30)
       └── Infrangible Broker Blocking Gate:
              ├── REJECTED ──► [ Block Execution ] ──► [ Structured Audit Log ]
              └── APPROVED ──► [ OptionExecutor ] ──► [ Structured Audit Log ]
                                      │
                                      ▼
                        [ Alpaca Paper Trading Broker ]
```

---

## 2. Core Features

### F1: Official Alpaca MCP & CLI Gateway (`src/execution/mcp_gateway.py`)
- **Python Stdio MCP Client (`StdioMCPTransport`)**: Full JSON-RPC 2.0 protocol implementation connecting to the official `alpaca-mcp-server` PyPI package via standard I/O pipes. Supports automatic tool discovery, environment propagation, and resilient reconnection with exponential backoff on broken pipes.
- **Alpaca CLI Transport (`CLITransport`)**: Direct integration with the pre-compiled Go binary at `/usr/bin/alpaca`, parsing structured JSON responses for account snapshots, market clock, and order placement.
- **Unified AlpacaGateway Facade**: Auto-negotiates the best available transport (`stdio` → `cli` → `mock`), eliminating direct ad-hoc REST SDK calls across `account.py`, `alpaca_executor.py`, and `main.py`.

### F2: Deterministic RiskEngine Guardrail (`src/risk/risk_engine.py`)
- **100% Exact Decimal Precision**: Zero floating-point representation errors using `decimal.Decimal` with `ROUND_HALF_UP`.
- **Infrangible 5% Single-Trade Rule**: Every trade cost is capped at $C_{\text{trade}} \le (V_{\text{portfolio}} \times 0.05)$, clamped to the effective buying power budget and cash availability.
- **Portfolio Options Cap**: Total cumulative options allocation cannot exceed 25% of portfolio equity.
- **Market Microstructure Guardrails**: Rejects crossed quotes ($P_{\text{bid}} \ge P_{\text{ask}}$), spreads $> 5.00\%$, and absolute dollar spreads $> \$0.50$.
- **Liquidity & Greeks Filters**: Requires open interest $\ge 500$, contract volume $\ge 100$, expiration $1 \le \text{DTE} \le 30$, Delta $\in [0.30, 0.70]$ (Calls) / $[-0.70, -0.30]$ (Puts), and daily Theta decay $\le 5.00\%$.
- **Hard Rejection Gate**: If `verdict.is_approved` is `False`, broker submission is physically impossible.

### F3: Execution Coordinator & Structured JSONL Logging
- **OptionExecutor (`src/execution/alpaca_executor.py`)**: Coordinates proposal approval, invokes `AlpacaGateway`, and dispatches audit events.
- **Dry-Run Simulation Mode (`--mode dry-run`)**: Simulates order fills with zero broker mutations, generating synthetic execution IDs and recording `TRADE_SIMULATED` audit records.
- **Auditable Structured JSONL Logging (`src/execution/trade_logger.py`)**: Draft-07 compliant log records written to `logs/trades.jsonl`, documenting market snapshots, agent proposals, risk verdicts, and execution results.

---

## 3. Structured Audit Log Schema (`logs/trades.jsonl`)

Every cycle produces a single-line JSON record adhering strictly to the Draft-07 JSON Schema:

```json
{
  "timestamp": "2026-09-03T14:30:00.123456+00:00",
  "event_type": "TRADE_EXECUTED",
  "mode": "scan",
  "market_data_snapshot": {
    "ticker": "SPY",
    "underlying_symbol": "SPY",
    "underlying_price": "500.00",
    "option_symbol": "SPY260930C00500000",
    "bid": "2.10",
    "bid_price": "2.10",
    "ask": "2.20",
    "ask_price": "2.20",
    "mid_price": "2.15",
    "spread_pct": "0.0465",
    "volume": 2000,
    "open_interest": 1500,
    "delta": "0.50",
    "theta": "-0.04",
    "dte": 20,
    "greeks": {
      "delta": "0.50",
      "gamma": "0.08",
      "theta": "-0.04",
      "vega": "0.12",
      "implied_volatility": "0.1850"
    }
  },
  "agent_proposal": {
    "strategy_name": "MomentumStrategy",
    "signal_type": "BULLISH_CALL_MOMENTUM",
    "confidence": "0.85",
    "target_contract_symbol": "SPY260930C00500000",
    "target_option_type": "CALL",
    "action": "BUY",
    "quantity": 2,
    "symbol": "SPY260930C00500000",
    "side": "buy",
    "rationale": "MomentumStrategy"
  },
  "risk_verdict": {
    "is_approved": true,
    "reason_code": "APPROVED",
    "message": "Trade passed all deterministic risk criteria",
    "trade_cost": "440.00",
    "max_allowed_budget": "5000.00",
    "portfolio_risk_pct_used": "0.0044",
    "reasons": [],
    "reason_codes": [],
    "warnings": [],
    "audited_metrics": {
      "trade_cost": 440.0,
      "max_allowed_risk": 5000.0,
      "portfolio_risk_pct": 0.44,
      "spread_pct": 4.65,
      "dte": 20
    }
  },
  "execution_result": {
    "executed": true,
    "execution_status": "FILLED",
    "order_id": "gw-order-888",
    "status": "filled",
    "filled_qty": 2,
    "filled_avg_price": "2.20"
  }
}
```

---

## 4. Installation & Setup

### Prerequisites
- Linux / macOS / Devcontainer
- Python 3.10+
- Alpaca Paper Trading Account API Keys

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `example.env` to `.env` and provide your credentials:
```bash
cp example.env .env
```
Edit `.env`:
```env
APCA_API_KEY_ID="your_paper_api_key_id"
APCA_API_SECRET_KEY="your_paper_api_secret_key"
APCA_API_BASE_URL="https://paper-api.alpaca.markets"
ALPACA_TOOLSETS="all"
```

---

## 5. CLI Usage & Execution Modes

The autonomous agent is launched via `src/main.py`:

### Scan Mode (Single Cycle on Paper Trading)
Scans the universe, screens liquidity, queries option chains via `AlpacaGateway`, evaluates proposals through `RiskEngine`, submits approved orders to Paper Trading, and records audit logs:
```bash
python src/main.py --mode scan --tickers AAPL,MSFT,SPY
```

### Dry-Run Mode (Simulation with Zero Broker Mutations)
Identical scanning and evaluation pipeline, but simulates fills locally without submitting orders to the broker:
```bash
python src/main.py --mode dry-run --tickers AAPL,MSFT,SPY
```

### Loop Mode (Continuous Real-Time Autonomous Operation)
Continuously executes scanning cycles at a specified interval:
```bash
python src/main.py --mode loop --interval 60 --tickers AAPL,MSFT,SPY
```

---

## 6. Test Verification Suite

The repository includes a comprehensive test suite across component unit tests and a 4-Tier Opaque-Box E2E verification suite.

### Running Unit Tests
```bash
# Gateway & Transport tests (24 tests)
python -m unittest tests/test_mcp_gateway.py -v

# Deterministic RiskEngine guardrail tests (27 tests)
python -m unittest tests/test_risk.py -v

# Execution coordinator, dry-run & logger tests
python -m unittest tests/test_execution.py -v

# Run all unit tests
python -m unittest discover -s tests -p "test_*.py" -v
```

### Running the 4-Tier Opaque-Box E2E Suite (140 Tests)
```bash
python tests/e2e/runner.py
```
Outputs structured pass/fail metrics across all 4 tiers:
- **Tier 1**: Feature Coverage (Features F1.1 – F3.2, 60 tests)
- **Tier 2**: Boundary & Corner Cases (Spreads, Greeks, DTE, Liquidity, 60 tests)
- **Tier 3**: Cross-Feature Combinations (Transports + Risk + Modes, 15 tests)
- **Tier 4**: Real-World Workload Scenarios (Momentum Breakout, Lottery Interception, Margin Stress, 5 tests)

---

## 7. Project Layout

```
├── .agents/                      # Multi-agent coordination metadata
├── docs/                         # Architecture, MCP, Risk, and Audit docs
│   ├── architecture.md           # System architecture specification
│   ├── mcp_integration.md        # MCP stdio & CLI integration guide
│   ├── risk_engine.md            # RiskEngine math & guardrail specification
│   └── audit_logging.md          # Draft-07 audit logging specification
├── logs/
│   └── trades.jsonl              # Append-only structured audit trail
├── src/
│   ├── account.py                # Account snapshot & health check utilities
│   ├── agents/                   # Autonomous strategy agent
│   ├── data/                     # Market data & liquidity screening
│   ├── execution/
│   │   ├── alpaca_executor.py    # OptionExecutor coordinator & MCP wrappers
│   │   ├── mcp_gateway.py        # AlpacaGateway (stdio, CLI, mock)
│   │   └── trade_logger.py       # TradeLogger JSONL Draft-07 implementation
│   ├── options/                  # OptionContract models, Greeks & chain filtering
│   ├── risk/
│   │   ├── models.py             # RiskReasonCode, RiskConfig, TradeProposal, RiskVerdict
│   │   └── risk_engine.py        # Deterministic 5% RiskEngine guardrail
│   └── main.py                   # Main CLI entrypoint (scan, dry-run, loop)
├── tests/
│   ├── e2e/                      # 4-Tier E2E test suite (140 tests)
│   ├── test_account.py           # Account snapshot tests
│   ├── test_execution.py         # OptionExecutor & TradeLogger tests
│   ├── test_mcp_gateway.py       # MCP & CLI transport tests
│   └── test_risk.py              # 17 RiskEngine scenario tests
├── pyproject.toml                # Build packaging & pytest configuration
└── requirements.txt              # Production and test dependencies
```

---

## 8. License
Apache 2.0 License. See `LICENSE` for details.
