# Alpaca AI Multi-Asset Autonomous Trading Agent / Agente Autónomo de Trading Multi-Activo Alpaca AI

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Alpaca MCP](https://img.shields.io/badge/Alpaca%20MCP-alpaca--mcp--server-green.svg)](https://github.com/alpacahq/alpaca-mcp-server)
[![Risk Engine](https://img.shields.io/badge/Risk%20Engine-5%25%20Infrangible%20Gate-red.svg)](src/risk/risk_engine.py)
[![Scalp & Quick-Trade](https://img.shields.io/badge/Execution-Scalp%20%7C%20Quick--Trade-purple.svg)](docs/scalp_and_quick_trade.md)
[![Audit Log](https://img.shields.io/badge/Audit%20Log-Draft--07%20JSONL-orange.svg)](logs/trades.jsonl)
[![Tests](https://img.shields.io/badge/Tests-4--Tier%20E2E%20%2B%20Unit-brightgreen.svg)](tests/e2e/runner.py)

[English](#english) | [Español](#español)

---

<a name="english"></a>
## English Documentation

### Overview
The **Alpaca AI Multi-Asset Autonomous Trading Agent** is a production-grade autonomous trading system combining the official Alpaca Model Context Protocol (MCP) server (`@alpacahq/mcp-server-alpaca` / `alpaca-mcp-server`) and the official Alpaca CLI (`/usr/bin/alpaca`).

The platform incorporates:
1. **Official Alpaca MCP & CLI Gateway (`src/execution/mcp_gateway.py`)**: Full stdio JSON-RPC 2.0 communication with the `"assets"` toolset, background stderr drain daemon, intelligent binary discovery, and automated unattended CLI authentication via `alpaca profile login --api-key`.
2. **Deterministic RiskEngine Guardrail (`src/risk/risk_engine.py`)**: Strict pre-trade filter enforcing the 5% portfolio risk rule with differentiated multipliers for equities ($1\times$) and options ($100\times$), safe sizing calculation, spread caps, and Greeks/DTE validation.
3. **Scalp & Fast-Trade Execution (`src/main.py`)**: High-frequency trading mode (`--mode scalp`) across 1Min/5Min bars and deterministic test trades (`--quick-trade`) featuring automatic equity fallback for immediate 24/7 web verification in the Alpaca Paper Trading dashboard (`https://app.alpaca.markets`).
4. **Draft-07 Auditable JSONL Logging (`src/execution/trade_logger.py`)**: Immutable audit trail in `logs/trades.jsonl` documenting market snapshots, agent proposals, risk verdicts, and execution results across `"scan"`, `"dry-run"`, `"loop"`, and `"scalp"` modes.

---

### 1. System Architecture

```
                      [ Market Data & Account State ]
                                     │
                                     ▼
                           [ AlpacaGateway Facade ]
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       ▼                             ▼                             ▼
[ StdioMCPTransport ]         [ CLITransport ]           [ MockMCPTransport ]
- Tools: get_clock,           - /usr/bin/alpaca          - Deterministic Offline
  get_calendar, assets        - Auto Profile Login         Simulations & Greeks
- Background Stderr Drain     - Non-interactive Stdin    - Zero External
- Multi-Asset Order Routing   - JSON Output Extraction     Dependencies
       │                             │                             │
       └─────────────────────────────┼─────────────────────────────┘
                                     │
                                     ▼
                       [ AI Strategy / Scalping Engine ]
                    (Micro-Momentum 1Min/5Min & Option Chains)
                                     │ (generates TradeProposal)
                                     ▼
                    [ Deterministic RiskEngine Guardrail ]
          ├── 5% Single-Trade Portfolio Risk Rule:
          │     ├── Equities: P_ask × 1 × Q ≤ V_portfolio × 0.05
          │     └── Options:  P_ask × 100 × Q ≤ V_portfolio × 0.05
          ├── Effective Buying Power & Cash Budget Clamping
          ├── Bid-Ask Spread Limits (Relative ≤ 5%, Absolute ≤ $0.50)
          ├── Options Greeks Horizons (Delta [0.30, 0.70], DTE 1-30, Theta ≤ 5%)
          └── Infrangible Pre-Trade Gate:
                ├── REJECTED ──► [ Block Broker Execution ] ──► [ Structured Audit Log ]
                └── APPROVED ──► [ OptionExecutor ]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
          [ Live / Paper Execution ]                  [ Dry-Run Simulation ]
          (Alpaca Paper Trading API)                  (Zero Broker Mutation)
                   │                                           │
                   ▼                                           ▼
       [ Alpaca Web Dashboard ]                       [ Draft-07 JSONL Log ]
       https://app.alpaca.markets                      logs/trades.jsonl
```

---

### 2. Multi-Asset 5% Portfolio Risk Rule

A critical innovation of Round 2 is the differentiated asset multiplier for single-trade risk enforcement:

$$\text{Trade Cost } (C_{\text{trade}}) = P_{\text{effective}} \times \text{Multiplier} \times Q$$

$$\text{Multiplier} = \begin{cases} 1 & \text{for Equities (Stocks & ETFs)} \\ 100 & \text{for Standard Options Contracts} \end{cases}$$

$$\text{Risk Engine Condition: } C_{\text{trade}} \le (V_{\text{portfolio}} \times 0.05)$$

#### Example Calculation ($100,000 Portfolio Value $\rightarrow$ $5,000 Maximum Trade Budget):
- **Equities (e.g. SPY @ $500.00/share)**:
  - 10 shares: $500.00 \times 1 \times 10 = \$5,000.00$ $\le \$5,000.00$ $\rightarrow$ **APPROVED**
  - 11 shares: $500.00 \times 1 \times 11 = \$5,500.00$ $> \$5,000.00$ $\rightarrow$ **REJECTED** (`ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`)
  - Maximum Safe Sizing: $Q_{\text{max\_safe}} = \lfloor \$5,000 / \$500 \rfloor = 10 \text{ shares}$.
- **Options (e.g. SPY Call @ $2.50/share $\rightarrow$ $250.00/contract)**:
  - 20 contracts: $\$2.50 \times 100 \times 20 = \$5,000.00$ $\le \$5,000.00$ $\rightarrow$ **APPROVED**
  - 25 contracts: $\$2.50 \times 100 \times 25 = \$6,250.00$ $> \$5,000.00$ $\rightarrow$ **REJECTED** (`ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`)
  - Maximum Safe Sizing: $Q_{\text{max\_safe}} = \lfloor \$5,000 / (\$2.50 \times 100) \rfloor = 20 \text{ contracts}$.

---

### 3. Alpaca MCP Toolsets & CLI Auto-Authentication

#### 3.1 The "assets" Toolset Configuration
In `alpaca-mcp-server` v2.3.1, `get_clock`, `get_calendar`, and `get_option_contracts` are located under the `"assets"` toolset. Omitting `"assets"` triggers `-32601: Unknown tool: 'get_clock'`.
The system configures:
```bash
ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data"
```

#### 3.2 CLI Unattended Authentication
`CLITransport` features automated non-interactive profile setup:
```bash
alpaca profile login --api-key
```
Credentials (`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`) are piped directly to stdin, enabling seamless execution in headless environments and CI/CD pipelines.

---

### 4. Instructions for Running the System

#### 4.1 Quick-Trade Mode (Immediate Web Verification)
Executes a deterministic 1-share test trade validated by `RiskEngine` for immediate verification in the Alpaca Web Dashboard:
```bash
# Execute against live Alpaca Paper Trading
python src/main.py --quick-trade

# Execute in dry-run simulation mode (zero broker calls)
python src/main.py --quick-trade --mode dry-run

# Custom ticker and asset type
python src/main.py --quick-trade --tickers AAPL --asset-type equity
```

#### 4.2 Scalp Mode (High-Frequency Micro-Momentum)
Runs fast scalping cycles on 1-minute or 5-minute bars with automatic equity fallback:
```bash
# 1-minute scalp scan
python src/main.py --mode scalp --timeframe 1Min

# 5-minute scalp scan with custom tickers
python src/main.py --mode scalp --timeframe 5Min --tickers SPY,AAPL,MSFT

# Scalp simulation in dry-run
python src/main.py --mode scalp --mode dry-run --timeframe 1Min

# Continuous scalp loop (every 30 seconds)
python src/main.py --mode scalp --timeframe 1Min --continuous --interval 30
```

#### 4.3 Standard Scan Mode (Options Swing Cycle)
Executes standard swing screening and options evaluation:
```bash
# Paper trading scan
python src/main.py --mode scan

# Dry-run simulation scan
python src/main.py --mode dry-run

# Continuous loop scan (every 60 seconds)
python src/main.py --mode loop --interval 60
```

#### 4.4 Verifying on the Alpaca Web Dashboard
When `--quick-trade` or `--mode scalp` executes, the console outputs:
```
[QUICK-TRADE SUCCESS] Order ID: a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d | Symbol: SPY | Qty: 1 | Status: filled
Dashboard Web: https://app.alpaca.markets
```
Open **[https://app.alpaca.markets](https://app.alpaca.markets)**, navigate to **Orders**, and verify the matching `Order ID`, `Symbol`, `Qty`, and `Status`.

---

### 5. Running the Test Verification Suite

The repository includes a 4-Tier E2E verification suite and comprehensive component unit tests:

```bash
# Run the complete 4-Tier E2E Test Suite (Tier 1 - Tier 4)
python tests/e2e/runner.py

# Discover and run all unit and integration tests
python -m unittest discover -s tests -p "test_*.py" -v

# Run MCP Gateway and Transport unit tests
python -m unittest tests/test_mcp_gateway.py -v

# Run Deterministic RiskEngine unit tests (TC-RSK-01 to TC-RSK-17 + Equity)
python -m unittest tests/test_risk.py -v

# Run Execution Coordinator, Fallback and TradeLogger tests
python -m unittest tests/test_execution.py -v

# Run Main CLI, Scalp Mode and Quick-Trade unit tests
python -m unittest tests/test_main.py -v

# Run Adversarial Risk and Hostile Broker Interception tests
python -m unittest tests/test_adversarial_risk.py -v
```

---

<a name="español"></a>
## Documentación en Español

### Descripción General
El **Agente Autónomo de Trading Multi-Activo Alpaca AI** es un sistema de trading institucional que integra el servidor oficial Model Context Protocol (MCP) de Alpaca (`@alpacahq/mcp-server-alpaca` / `alpaca-mcp-server`) y el CLI oficial de Alpaca (`/usr/bin/alpaca`).

El sistema incorpora:
1. **Gateway Oficial Alpaca MCP y CLI (`src/execution/mcp_gateway.py`)**: Comunicación stdio JSON-RPC 2.0 con el toolset `"assets"`, hilo demonio para vaciado continuo de stderr, auto-descubrimiento de binarios y autenticación desatendida del CLI mediante `alpaca profile login --api-key`.
2. **Motor de Riesgo Determinista (`src/risk/risk_engine.py`)**: Filtro pre-trade estricto que aplica la regla del 5% con multiplicadores diferenciados para acciones ($1\times$) y opciones ($100\times$), dimensionamiento seguro automático, límites de spread y validación de griegas/DTE.
3. **Modo Scalping y Fast-Trade (`src/main.py`)**: Modo de alta frecuencia (`--mode scalp`) con barras de 1Min/5Min y órdenes de prueba deterministas (`--quick-trade`) con fallback automático a acciones para verificación 24/7 en el dashboard web de Alpaca Paper Trading (`https://app.alpaca.markets`).
4. **Auditoría Estructurada JSONL Draft-07 (`src/execution/trade_logger.py`)**: Registro inmutable en `logs/trades.jsonl` con instantáneas de mercado, propuestas de agentes, veredictos de riesgo y resultados de ejecución en modos `"scan"`, `"dry-run"`, `"loop"` y `"scalp"`.

---

### 1. Arquitectura del Sistema

```
                      [ Datos de Mercado y Estado de Cuenta ]
                                         │
                                         ▼
                            [ Fachada AlpacaGateway ]
                                         │
       ┌─────────────────────────────────┼─────────────────────────────────┐
       ▼                                 ▼                                 ▼
[ StdioMCPTransport ]             [ CLITransport ]               [ MockMCPTransport ]
- Herramientas: get_clock,        - Binario /usr/bin/alpaca      - Pruebas deterministas
  get_calendar, assets            - Auto-login de perfil           offline y griegas
- Drenaje de stderr en demonio    - Stdin no interactivo         - Cero dependencias
- Enrutamiento multi-activo       - Extracción JSON                externas
       │                                 │                                 │
       └─────────────────────────────────┼─────────────────────────────────┘
                                         │
                                         ▼
                        [ Motor de Estrategia / Scalping ]
                      (Micro-momentum 1Min/5Min y Opciones)
                                         │ (genera TradeProposal)
                                         ▼
                      [ Guardarraíl Determinista RiskEngine ]
          ├── Regla del 5% del Portafolio por Trade:
          │     ├── Acciones: P_ask × 1 × Q ≤ V_cartera × 0.05
          │     └── Opciones: P_ask × 100 × Q ≤ V_cartera × 0.05
          ├── Límite de Presupuesto Efectivo (Cash y Buying Power)
          ├── Guardarraíles de Spread (Relativo ≤ 5%, Absoluto ≤ $0.50)
          ├── Horizontes de Opciones (Delta [0.30, 0.70], DTE 1-30, Theta ≤ 5%)
          └── Puerta Infranqueable Pre-Trade:
                ├── RECHAZADO ──► [ Bloqueo Físico en Broker ] ──► [ Bitácora de Auditoría ]
                └── APROBADO  ──► [ OptionExecutor ]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
          [ Ejecución Paper Trading ]                 [ Simulación Dry-Run ]
          (API Alpaca Paper Trading)                  (Cero mutación en broker)
                   │                                           │
                   ▼                                           ▼
       [ Dashboard Web Alpaca ]                       [ Bitácora Draft-07 ]
       https://app.alpaca.markets                      logs/trades.jsonl
```

---

### 2. Regla del 5% de Riesgo de Cartera Multi-Activo

Una innovación esencial de la Ronda 2 es el multiplicador diferenciado para calcular el costo y riesgo de cada trade:

$$\text{Costo del Trade } (C_{\text{trade}}) = P_{\text{efectivo}} \times \text{Multiplicador} \times Q$$

$$\text{Multiplicador} = \begin{cases} 1 & \text{para Acciones y ETFs} \\ 100 & \text{para Contratos de Opciones Estándar} \end{cases}$$

$$\text{Condición del RiskEngine: } C_{\text{trade}} \le (V_{\text{cartera}} \times 0.05)$$

#### Ejemplo Práctico (Cartera de $100,000 $\rightarrow$ Límite Máximo de $5,000 por Trade):
- **Acciones (ej. SPY a $500.00 por acción)**:
  - 10 acciones: $500.00 \times 1 \times 10 = \$5,000.00$ $\le \$5,000.00$ $\rightarrow$ **APROBADO**
  - 11 acciones: $500.00 \times 1 \times 11 = \$5,500.00$ $> \$5,000.00$ $\rightarrow$ **RECHAZADO** (`ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`)
  - Tamaño seguro calculado: $Q_{\text{seguro}} = \lfloor \$5,000 / \$500 \rfloor = 10 \text{ acciones}$.
- **Opciones (ej. Call SPY a $2.50 por acción $\rightarrow$ $250.00 por contrato)**:
  - 20 contratos: $\$2.50 \times 100 \times 20 = \$5,000.00$ $\le \$5,000.00$ $\rightarrow$ **APROBADO**
  - 25 contratos: $\$2.50 \times 100 \times 25 = \$6,250.00$ $> \$5,000.00$ $\rightarrow$ **RECHAZADO** (`ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`)
  - Tamaño seguro calculado: $Q_{\text{seguro}} = \lfloor \$5,000 / (\$2.50 \times 100) \rfloor = 20 \text{ contratos}$.

---

### 3. Toolsets de Alpaca MCP y Autenticación de Alpaca CLI

#### 3.1 Configuración del Toolset "assets"
En `alpaca-mcp-server` v2.3.1, las funciones `get_clock`, `get_calendar` y `get_option_contracts` pertenecen al conjunto `"assets"`. Su omisión genera el error `-32601: Unknown tool: 'get_clock'`.
El sistema establece:
```bash
ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data"
```

#### 3.2 Autenticación Desatendida de Alpaca CLI
`CLITransport` incluye configuración automática sin interacción humana:
```bash
alpaca profile login --api-key
```
Las credenciales se canalizan por `stdin`, permitiendo ejecución continua en entornos desatendidos y contenedores.

---

### 4. Instrucciones de Ejecución

#### 4.1 Modo Quick-Trade (Verificación Web Inmediata)
Genera una orden determinista de 1 acción validada por el `RiskEngine` para corroborar de inmediato su aparición en la web de Alpaca:
```bash
# Ejecución real en Alpaca Paper Trading
python src/main.py --quick-trade

# Ejecución en simulación local dry-run (sin llamadas al broker)
python src/main.py --quick-trade --mode dry-run

# Ticker personalizado y tipo de activo
python src/main.py --quick-trade --tickers AAPL --asset-type equity
```

#### 4.2 Modo Scalping (Alta Frecuencia con Micro-Momentum)
Ejecuta ciclos rápidos sobre velas de 1 o 5 minutos con fallback automático a acciones:
```bash
# Escaneo de scalping con velas de 1 minuto
python src/main.py --mode scalp --timeframe 1Min

# Escaneo con velas de 5 minutos y tickers personalizados
python src/main.py --mode scalp --timeframe 5Min --tickers SPY,AAPL,MSFT

# Simulación de scalping en modo dry-run
python src/main.py --mode scalp --mode dry-run --timeframe 1Min

# Bucle continuo de scalping (cada 30 segundos)
python src/main.py --mode scalp --timeframe 1Min --continuous --interval 30
```

#### 4.3 Modo Scan Estándar (Ciclo Swing de Opciones)
Ejecuta escaneo estándar de opciones:
```bash
# Escaneo en Paper Trading
python src/main.py --mode scan

# Simulación dry-run
python src/main.py --mode dry-run

# Bucle continuo (cada 60 segundos)
python src/main.py --mode loop --interval 60
```

#### 4.4 Verificación en el Dashboard Web de Alpaca
Al ejecutar `--quick-trade` o `--mode scalp`, la consola reporta:
```
[QUICK-TRADE SUCCESS] Order ID: a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d | Symbol: SPY | Qty: 1 | Status: filled
Dashboard Web: https://app.alpaca.markets
```
Abra **[https://app.alpaca.markets](https://app.alpaca.markets)**, ingrese a la sección **Orders** y confirme la presencia de la orden con su `Order ID`, `Symbol`, `Qty` y `Status`.

---

### 5. Ejecución de la Suite de Pruebas

```bash
# Ejecutar la suite completa de 4 niveles E2E (Tier 1 a Tier 4)
python tests/e2e/runner.py

# Descubrir y ejecutar todos los tests unitarios e integrados
python -m unittest discover -s tests -p "test_*.py" -v

# Pruebas unitarias de Gateway y Transportes MCP/CLI
python -m unittest tests/test_mcp_gateway.py -v

# Pruebas unitarias del Motor de Riesgo Determinista
python -m unittest tests/test_risk.py -v

# Pruebas del Coordinador de Ejecución, Fallback y TradeLogger
python -m unittest tests/test_execution.py -v

# Pruebas del CLI Principal, Modo Scalp y Quick-Trade
python -m unittest tests/test_main.py -v

# Pruebas Adversariales e Intercepción de Broker Hostil
python -m unittest tests/test_adversarial_risk.py -v
```

---

### 6. Documentación Técnica Detallada / Detailed Technical Docs

Para especificaciones en profundidad, consulte los documentos en `docs/`:
- **[MCP & CLI Integration Guide](docs/mcp_integration.md)**: Arquitectura de transportes, toolset `assets`, drenaje de stderr y auto-auth.
- **[Scalping & Quick-Trade Guide](docs/scalp_and_quick_trade.md)**: Modo scalp, quick-trade, fallback a acciones y verificación web en Alpaca.
- **[Deterministic RiskEngine Specification](docs/risk_engine.md)**: Fórmulas matemáticas multi-activo, regla del 5% y guardarraíles pre-trade.
- **[Draft-07 Audit Logging Specification](docs/audit_logging.md)**: Estructura JSONL, esquemas y trazabilidad en `logs/trades.jsonl`.
- **[System Architecture](docs/architecture.md)**: Diagramas y diseño de componentes del sistema.

---

### 7. Estructura del Proyecto / Project Layout

```
├── docs/                         # Documentación técnica bilingüe
│   ├── architecture.md           # Especificación de arquitectura general
│   ├── audit_logging.md          # Bitácora JSONL conforme a Draft-07
│   ├── mcp_integration.md        # Integración de Alpaca MCP y CLI
│   ├── risk_engine.md            # Especificación matemática del RiskEngine
│   └── scalp_and_quick_trade.md  # Modo scalping, quick-trade y verificación web
├── logs/
│   └── trades.jsonl              # Bitácora inmutable de auditoría
├── src/
│   ├── account.py                # Snapshot de cuenta y chequeo de salud
│   ├── agents/                   # Agentes autónomos de estrategia
│   ├── data/                     # Ingesta de mercado y filtro de liquidez
│   ├── execution/
│   │   ├── alpaca_executor.py    # OptionExecutor, execute_equity_trade, fallback
│   │   ├── mcp_gateway.py        # AlpacaGateway (stdio, CLI, mock)
│   │   └── trade_logger.py       # TradeLogger JSONL Draft-07 multi-activo
│   ├── options/                  # Modelos de opciones, griegas y cadenas
│   ├── risk/
│   │   ├── models.py             # TradeProposal multi-activo y RiskVerdict
│   │   └── risk_engine.py        # RiskEngine determinista (regla del 5%)
│   └── main.py                   # Entry point (scan, dry-run, loop, scalp, quick-trade)
├── tests/
│   ├── e2e/                      # Runner E2E de 4 niveles y fixtures
│   ├── test_account.py           # Pruebas de cuenta y clock
│   ├── test_adversarial_risk.py  # Pruebas adversariales de riesgo
│   ├── test_execution.py         # Pruebas de OptionExecutor y TradeLogger
│   ├── test_main.py              # Pruebas de CLI, scalp y quick-trade
│   ├── test_mcp_gateway.py       # Pruebas de Gateway, toolsets y CLI auto-auth
│   └── test_risk.py              # Pruebas de RiskEngine (opciones y acciones)
├── pyproject.toml
└── requirements.txt
```

---

### 8. Licencia / License
Apache 2.0 License.
