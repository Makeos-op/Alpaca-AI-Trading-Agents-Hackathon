# Alpaca MCP & CLI Gateway Integration

## Overview

The `AlpacaGateway` class (`src/execution/mcp_gateway.py`) fulfills Hackathon Requirement R1 by providing unified, protocol-compliant access to Alpaca Paper Trading via the official Model Context Protocol (MCP) server or the official Alpaca CLI.

---

## 1. Transport Hierarchy

The gateway implements a multi-tier transport architecture via `BaseAlpacaTransport`:

```
               [ AlpacaGateway(mode="auto") ]
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
   [ StdioMCPTransport ]  [ CLITransport ]  [ MockMCPTransport ]
   (Primary Protocol)    (Local Fallback)   (Test/Simulation)
```

### Tier 1: StdioMCPTransport
- Communicates with `alpaca-mcp-server` (alpacahq/alpaca-mcp-server on PyPI) launched via `uvx`.
- Implements JSON-RPC 2.0 protocol over `stdin`/`stdout`.
- Features:
  * Dynamic FastMCP tool discovery (`tools/list`).
  * Structured tool invocation (`tools/call`).
  * Automatic pipe reconnect with exponential backoff on broken streams.
  * Paper trading environment configuration via `APCA_API_BASE_URL` and `ALPACA_TOOLSETS`.

### Tier 2: CLITransport
- Subprocess execution wrapper invoking `/usr/bin/alpaca` with `--format json`.
- Executes commands:
  * `alpaca account get --format json`
  * `alpaca market clock --format json`
  * `alpaca position list --format json`
  * `alpaca order submit --symbol <sym> --qty <qty> --side <side> --type <type> --format json`
- Handles errors through `CLIExecutionError`.

### Tier 3: MockMCPTransport
- Deterministic, in-memory transport for unit testing and offline development.
- Provides realistic account state, market clocks, and dynamic option chain generation with exact Black-Scholes Greeks ($\Delta, \Gamma, \Theta, \nu, \text{IV}$).
- Supports failure and error injection for resilience verification.

---

## 2. Gateway Interface Contract

The gateway exposes a clean, synchronous interface:

```python
class AlpacaGateway:
    def __init__(self, mode: str = "auto", paper: bool = True): ...
    def get_account(self) -> AccountSnapshot: ...
    def get_clock(self) -> MarketClock: ...
    def get_option_chain(self, underlying: str, min_dte: int = 1, max_dte: int = 30) -> list[OptionContract]: ...
    def submit_option_order(self, symbol: str, qty: int, side: str, time_in_force: str = "day", **kwargs) -> dict: ...
```

### Auto-Negotiation Logic
When `mode="auto"`:
1. Gateway attempts initialization of `StdioMCPTransport`.
2. If `uvx` or a Python/uv environment is unavailable, it gracefully falls back to `CLITransport`.
3. If `/usr/bin/alpaca` is unavailable (e.g. in test containers), it activates `MockMCPTransport`, logging a diagnostic notification.
