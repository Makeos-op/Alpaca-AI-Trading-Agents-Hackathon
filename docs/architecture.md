# Architecture Specification

## Overview

The **Alpaca AI Options Autonomous Trading System** is designed to provide institutional-grade safety, deterministic risk enforcement, and protocol compliance for autonomous options trading on Alpaca Paper Trading.

The architecture solves two fundamental challenges in LLM-assisted and autonomous trading systems:
1. **Protocol Rigidity**: Standardizing all broker communications through official MCP stdio (`alpaca-mcp-server`, PyPI package alpacahq/alpaca-mcp-server) or Alpaca CLI (`/usr/bin/alpaca`), preventing fragmented, unauthorized direct REST calls.
2. **Hallucination Interception**: Enforcing an infrangible, deterministic pre-trade risk guardrail (`RiskEngine`) with 100% Decimal precision that physically blocks out-of-bounds orders before any broker API interaction can occur.

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Market Environment                             │
│                  Alpaca Paper Trading / Market Data                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    AlpacaGateway (Unified Facade)                       │
│    src/execution/mcp_gateway.py                                         │
│    ├── StdioMCPTransport (FastMCP stdio JSON-RPC 2.0 via uvx)          │
│    ├── CLITransport (Subprocess wrapper for /usr/bin/alpaca JSON)       │
│    └── MockMCPTransport (Deterministic offline simulator)               │
└──────────────────┬──────────────────────────────────┬───────────────────┘
                   │                                  │
    Account State  │                   Option Chains  │
    & Market Clock │                   & Quotes       │
                   ▼                                  ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────┐
│   Account Health & Budget Analysis   │  │   Market Screening & Strategy │
│   src/account.py                     │  │   src/data/, src/agents/      │
└──────────────────┬───────────────────┘  └───────────────┬───────────────┘
                   │                                      │
                   │  Effective Buying Power Budget       │ TradeProposal
                   └──────────────────┬───────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             Deterministic RiskEngine (Infrangible Guardrail)            │
│    src/risk/risk_engine.py & src/risk/models.py                         │
│    ├── 5% Single-Trade Portfolio Equity Limit                           │
│    ├── Effective Buying Power & Cash Clamping                           │
│    ├── 25% Cumulative Options Allocation Cap                            │
│    ├── Bid-Ask Spread Filters (≤ 5.00%, ≤ $0.50) & Crossed Quotes Check │
│    ├── Liquidity Filters (Volume ≥ 100, Open Interest ≥ 500)            │
│    └── Greeks & Expiration Filters (DTE 1-30, Delta [0.3, 0.7], Theta) │
└──────────────────┬──────────────────────────────────┬───────────────────┘
                   │                                  │
         REJECTED  │                         APPROVED │
                   ▼                                  ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────┐
│        Broker Call Blocked           │  │   OptionExecutor Coordinator  │
│        Zero Broker Mutation          │  │   src/execution/alpaca_executor.py│
└──────────────────┬───────────────────┘  └───────────────┬───────────────┘
                   │                                      │
                   │                                      │ Live or
                   │                                      │ Dry-Run Sim
                   ▼                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  Auditable Structured JSONL Logger                      │
│    src/execution/trade_logger.py -> logs/trades.jsonl                   │
│    Draft-07 Compliant: Snapshot, Proposal, Verdict, Execution Result   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow & Invariants

### Invariant 1: Infrangible Pre-Trade Blocking
Under no circumstance can a trade proposal reach Alpaca Paper Trading without passing `RiskEngine.evaluate_trade()`.
If `verdict.is_approved == False`:
- Broker submission is never invoked.
- `OptionExecutor` returns `ExecutionResult(success=False, status="REJECTED")`.
- `TradeLogger` appends a `TRADE_REJECTED` record to `logs/trades.jsonl`.

### Invariant 2: Zero Broker Mutation in Dry-Run Mode
When launched with `--mode dry-run`:
- Scanning, analysis, and RiskEngine evaluation occur identically to live/paper execution.
- If approved, `OptionExecutor` synthesizes an order ID (`dry-run-order-...`) and returns `status="SIMULATED"`.
- `TradeLogger` records `event_type="TRADE_SIMULATED"` and `mode="dry-run"`.
- No HTTP or stdio order execution is transmitted to Alpaca.

### Invariant 3: Audit Trail Immutability
All evaluated proposals—whether approved, simulated, or rejected—produce an immutable, append-only record in `logs/trades.jsonl` matching the Draft-07 JSON Schema specification.
