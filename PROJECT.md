# Project: Alpaca AI Trading Agents Hackathon — Round 2

## Architecture
- **Transport & Gateway Layer (`src/execution/mcp_gateway.py`)**:
  - `StdioMCPTransport`: Connects to official `alpaca-mcp-server` / `@alpacahq/mcp-server-alpaca` via JSON-RPC 2.0 stdio with `ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data"`. Implements binary auto-discovery (`alpaca-mcp-server` -> `uvx` -> `sys.executable -m alpaca_mcp_server` -> `npx`), stderr reader daemon, 15s handshake timeout, and multi-asset routing (`place_stock_order` vs `place_option_order`).
  - `CLITransport`: Connects to `/usr/bin/alpaca` (Go OpenAPI CLI v0.0.13). Implements `is_authenticated()` and `auto_configure_profile()` via `alpaca profile login --api-key` with stdin credential piping (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`) and direct environment variable forwarding.
  - `MockMCPTransport`: Fully deterministic offline simulation mock.
  - `AlpacaGateway`: High-level facade exposing unified methods for account, clock, calendar, option chains, stock quotes, and order submissions (`submit_stock_order`, `submit_option_order`, `submit_order`).
- **Risk Guardrail Layer (`src/risk/risk_engine.py`, `src/risk/models.py`)**:
  - Deterministic pre-trade validation enforcing strict 5% single-trade portfolio limit ($P_{ask} \times Q \le V_{portfolio} \times 0.05$ for equities; $P_{ask} \times 100 \times Q \le V_{portfolio} \times 0.05$ for options).
  - Effective cash / buying power budget calculation ($\min(L_{single\_risk}, BP, C_{cash})$).
  - Multi-asset support: options evaluate Greeks (delta, theta), DTE (1-30), and open interest; equities evaluate price, spread, liquidity, and portfolio risk while safely bypassing Greeks/DTE.
  - Mandatory hard guardrail: `verdict.is_approved` must be `True` for order submission; otherwise execution is blocked with zero broker calls.
- **Execution & Logging Layer (`src/execution/alpaca_executor.py`, `src/execution/trade_logger.py`)**:
  - `OptionExecutor`: Orchestrates pre-trade risk evaluation, order submission via `AlpacaGateway`, and fallback to equity orders (SPY, AAPL) when option contracts are illiquid or markets are closed.
  - `TradeLogger`: Writes Draft-07 compliant audit logs to `logs/trades.jsonl` recording market data snapshot, agent proposal, risk verdict, and broker execution result.
- **Application CLI & Modes (`src/main.py`)**:
  - Modes: `scan`, `loop`, `dry-run`, and `scalp` (1Min/5Min timeframe fast evaluation).
  - Flag: `--quick-trade` for immediate deterministic test trade execution, printing Order ID and Alpaca Paper Trading dashboard link (`https://app.alpaca.markets`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F-MCP-01 | Configurar `ALPACA_TOOLSETS` con `"assets"` (`"account,trading,assets,options-data,stock-data"`) | M1 | R1 Spec |
| 2 | F-MCP-02 | Stdio binary auto-discovery (`alpaca-mcp-server`, `uvx`, `sys.executable -m alpaca_mcp_server`, `npx`) | M1 | R1 Spec |
| 3 | F-MCP-03 | Stdio handshake stability, stderr consumer daemon, and prevention of unexpected mock fallback | M1 | R1 Spec |
| 4 | F-MCP-04 | Habilitar y verificar `get_clock`, `get_calendar`, y `get_option_contracts` | M1 | R1 Spec |
| 5 | F-CLI-01 | Detección de autenticación CLI (`is_authenticated`) vía `alpaca account get` | M1 | R2 Spec |
| 6 | F-CLI-02 | Auto-configuración no interactiva CLI vía `alpaca profile login --api-key` con stdin | M1 | R2 Spec |
| 7 | F-CLI-03 | Inyección de credenciales `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` en entorno de ejecución CLI | M1 | R2 Spec |
| 8 | F-RSK-01 | Diferenciación de multiplicador en regla del 5%: 1x para acciones/ETFs vs 100x para opciones | M2 | R3 Spec |
| 9 | F-RSK-02 | Bypass seguro de filtros de opciones (DTE, Greeks, open interest) para propuestas de acciones | M2 | R3 Spec |
| 10 | F-RSK-03 | Intercepción obligatoria en `RiskEngine` con bloqueo estricto si `is_approved == False` | M2 | R3 Spec |
| 11 | F-EXE-01 | Soporte multi-activo en Gateway: `place_stock_order` para acciones y `place_option_order` para opciones | M1 | R3 Spec |
| 12 | F-EXE-02 | Soporte de órdenes de acciones/ETFs (SPY, AAPL) con fallback cuando opciones no están disponibles | M2 | R3 Spec |
| 13 | F-EXE-03 | Logging estructurado Draft-07 en `logs/trades.jsonl` para órdenes de acciones y modo scalp | M2 | R3 Spec |
| 14 | F-APP-01 | Modo `--mode scalp` con temporalidades rápidas (1Min / 5Min) | M3 | R3 Spec |
| 15 | F-APP-02 | Flag `--quick-trade` para ejecución inmediata de orden de test validada por `RiskEngine` | M3 | R3 Spec |
| 16 | F-APP-03 | Impresión en consola de Order ID y URL de verificación web en Paper Trading (`https://app.alpaca.markets`) | M3 | R3 Spec |
| 17 | F-TST-01 | Actualización y expansión de tests unitarios (`test_mcp_gateway`, `test_risk`, `test_execution`) | M4 | R4 Spec |
| 18 | F-TST-02 | Actualización de fixtures y suite E2E de 4 tiers para soportar toolsets, CLI auto-auth y modo scalp | M4 | R4 Spec |
| 19 | F-DOC-01 | Documentación completa y bilingüe (español/inglés) en `docs/` y `README.md` | M4 | R4 Spec |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: MCP Toolset & CLI Core | `src/execution/mcp_gateway.py`: `ALPACA_TOOLSETS` con `"assets"`, binary discovery, stderr consumer, `get_clock`/`get_calendar`, CLI auto-auth, `place_stock_order` | none | **DONE** |
| 2 | M2: RiskEngine Guardrail & Multi-Asset Execution | `src/risk/risk_engine.py`, `src/risk/models.py`, `src/execution/alpaca_executor.py`, `src/execution/trade_logger.py`: 5% rule 1x vs 100x, equity order fallback, Draft-07 logging | M1 | **DONE** |
| 3 | M3: Scalp & Quick-Trade Application Entry Point | `src/main.py`: `--mode scalp` (1M/5M), `--quick-trade`, RiskEngine wiring, console Order ID & URL output | M2 | **DONE** |
| 4 | M4: Test Suite & Documentation Track | `tests/`, `tests/e2e/`, `docs/`, `README.md`: New unit & E2E tests, 100% test pass verification, bilingual documentation | M3 | **DONE** |

## Interface Contracts
### `AlpacaGateway` ↔ `OptionExecutor` / Application
- `gw.get_clock() -> MarketClockInfo`: Returns market clock with `is_open`, `next_open`, `next_close`.
- `gw.get_calendar(start, end) -> List[Dict]`: Returns trading calendar days.
- `gw.submit_stock_order(symbol: str, qty: int, side: str, order_type: str = "market", time_in_force: str = "day") -> Dict[str, Any]`: Dispatches `place_stock_order` in MCP or `alpaca order submit` in CLI. Returns `{ "order_id": str, "status": str, "symbol": str, "qty": int, "side": str }`.
- `gw.submit_option_order(symbol: str, qty: int, side: str, order_type: str = "market", time_in_force: str = "day") -> Dict[str, Any]`: Dispatches `place_option_order` in MCP.
- `gw.submit_order(symbol: str, qty: int, side: str, order_type: str = "market", time_in_force: str = "day") -> Dict[str, Any]`: Auto-detects OCC option symbol vs equity ticker and routes accordingly.

### `RiskEngine` ↔ `OptionExecutor`
- `engine.evaluate_proposal(proposal: TradeProposal, portfolio: PortfolioState, market_data: MarketDataSnapshot) -> RiskVerdict`:
  - `proposal.asset_class`: `"equity"` or `"option"`.
  - For `"equity"`: `trade_cost = ask_price * quantity` (multiplier 1). Enforces 5% portfolio limit: `trade_cost <= portfolio.equity * 0.05`. Enforces cash/buying power: `trade_cost <= min(portfolio.buying_power, portfolio.cash)`. Bypasses Greeks and DTE.
  - For `"option"`: `trade_cost = ask_price * 100 * quantity`. Enforces 5% portfolio limit, Greeks, DTE (1-30), liquidity.
  - `RiskVerdict`: `is_approved: bool`, `reasons: List[str]`, `max_approved_quantity: int`.

## Code Layout
- `src/execution/mcp_gateway.py`: MCP and CLI transports and gateway facade (M1).
- `src/risk/risk_engine.py`: Deterministic risk engine and limit verification (M2).
- `src/risk/models.py`: Risk data classes and trade proposals (M2).
- `src/execution/alpaca_executor.py`: Trade executor with risk check and equity fallback (M2).
- `src/execution/trade_logger.py`: Structured Draft-07 JSONL logging (M2).
- `src/main.py`: CLI arguments (`--mode scalp`, `--quick-trade`), trading loop orchestration (M3).
- `tests/`: Unit and adversarial test suites (M4).
- `tests/e2e/`: Opaque-box 4-tier E2E testing framework (M4).
- `docs/`: Technical documentation in Spanish and English (M4).
- `README.md`: Project overview and usage instructions (M4).
