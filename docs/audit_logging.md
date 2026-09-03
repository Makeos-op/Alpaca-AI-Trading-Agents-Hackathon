# Draft-07 Structured JSONL Audit Logging / Bitácora de Auditoría Estructurada Draft-07

[English](#english) | [Español](#español)

---

<a name="english"></a>
## English Documentation

### Overview
The `TradeLogger` (`src/execution/trade_logger.py`) implements an immutable, append-only structured logging mechanism fulfilling Hackathon Requirement R3. Every evaluation and execution cycle generates an auditable record conforming strictly to the **JSON Schema Draft-07** specification, persisted to:
```
logs/trades.jsonl
```

### 1. Top-Level Schema Specification

Each record in `logs/trades.jsonl` is a valid, independent JSON object with the following top-level fields:

| Field | Type | Description | Allowed Values |
|---|---|---|---|
| `timestamp` | string | ISO-8601 UTC timestamp | Format: `YYYY-MM-DDTHH:MM:SS.ffffff+00:00` |
| `event_type` | string | Nature of the logged event | `"TRADE_EXECUTED"`, `"TRADE_REJECTED"`, `"TRADE_SIMULATED"` |
| `mode` | string | Operational execution mode | `"scan"`, `"dry-run"`, `"loop"`, `"scalp"` |
| `market_data_snapshot` | object | Quotes, liquidity and Greeks | See Section 2.1 |
| `agent_proposal` | object | Proposed trade parameters | See Section 2.2 |
| `risk_verdict` | object | Deterministic RiskEngine verdict | See Section 2.3 |
| `execution_result` | object | Broker order result or simulation | See Section 2.4 |

### 2. Multi-Asset Draft-07 Schema Compliance

To guarantee 100% compliance across both option contracts and equities (shares/ETFs):
- **Equities (Scalp & Quick-Trade)**:
  - `asset_class`: `"equity"`
  - Synthetic and neutral indicators satisfy the schema: `target_option_type="EQUITY"`, `option_symbol=ticker`, `dte=0`, `delta="1.00"`, `greeks={"delta": "1.00", "gamma": "0.00", "theta": "0.00", "vega": "0.00", "implied_volatility": "0.00"}`.
  - Multiplier is $1$, so `trade_cost` is $P_{\text{ask}} \times Q$.
- **Options**:
  - `asset_class`: `"option"`
  - Populates OCC option symbol, Black-Scholes Greeks ($\Delta, \Gamma, \Theta, \nu, \text{IV}$), DTE, and multiplier $100$.

### 3. Record Examples

#### 3.1 Executed Equity Scalp Trade (`mode: "scalp"`)
```json
{
  "timestamp": "2026-09-03T14:35:10.512400+00:00",
  "event_type": "TRADE_EXECUTED",
  "mode": "scalp",
  "market_data_snapshot": {
    "ticker": "SPY",
    "underlying_symbol": "SPY",
    "underlying_price": "500.00",
    "bid_price": "500.00",
    "ask_price": "500.05",
    "mid_price": "500.025",
    "spread_pct": "0.0001",
    "volume": 1000000,
    "open_interest": 0,
    "greeks": {
      "delta": "1.00",
      "gamma": "0.00",
      "theta": "0.00",
      "vega": "0.00",
      "implied_volatility": "0.00"
    }
  },
  "agent_proposal": {
    "strategy_name": "QuickTradeDeterministic",
    "signal_type": "QUICK_TRADE",
    "confidence": "1.00",
    "target_option_type": "EQUITY",
    "action": "BUY",
    "quantity": 1,
    "symbol": "SPY",
    "side": "buy",
    "rationale": "Deterministic test trade for web dashboard verification (SPY)"
  },
  "risk_verdict": {
    "is_approved": true,
    "reason_code": "APPROVED",
    "trade_cost": "500.05",
    "max_allowed_budget": "5000.00",
    "portfolio_risk_pct_used": "0.0050",
    "reasons": [],
    "reason_codes": []
  },
  "execution_result": {
    "executed": true,
    "execution_status": "FILLED",
    "order_id": "9f8e7d6c-5b4a-3f2e-1d0c-9b8a7f6e5d4c",
    "status": "filled",
    "filled_qty": 1,
    "filled_avg_price": "500.05"
  }
}
```

#### 3.2 Rejected Trade (Risk Violation in Scalp Mode)
```json
{
  "timestamp": "2026-09-03T14:36:00.000000+00:00",
  "event_type": "TRADE_REJECTED",
  "mode": "scalp",
  "market_data_snapshot": { ... },
  "agent_proposal": {
    "strategy_name": "ScalpFastMomentum",
    "action": "BUY",
    "quantity": 25,
    "symbol": "SPY"
  },
  "risk_verdict": {
    "is_approved": false,
    "reason_code": "ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT",
    "trade_cost": "12501.25",
    "max_allowed_budget": "5000.00",
    "portfolio_risk_pct_used": "0.1250",
    "reasons": ["El costo del trade ($12501.25) excede el límite del 5.0% máximo por operación ($5000.00)."],
    "reason_codes": ["ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT"]
  },
  "execution_result": {
    "executed": false,
    "execution_status": "REJECTED",
    "order_id": null,
    "status": "rejected",
    "filled_qty": 0,
    "filled_avg_price": null
  }
}
```

---

<a name="español"></a>
## Documentación en Español

### Descripción General
`TradeLogger` (`src/execution/trade_logger.py`) implementa una bitácora inmutable de solo adición cumpliendo el Requisito R3 del Hackathon. Cada evaluación y ejecución genera un registro auditable conforme a la especificación **JSON Schema Draft-07** en:
```
logs/trades.jsonl
```

### 1. Especificación del Esquema de Primer Nivel

Cada línea en `logs/trades.jsonl` es un objeto JSON independiente con siete claves obligatorias:

| Campo | Tipo | Descripción | Valores Permitidos |
|---|---|---|---|
| `timestamp` | string | Marca temporal UTC en formato ISO-8601 | Formato: `YYYY-MM-DDTHH:MM:SS...` |
| `event_type` | string | Tipo de evento registrado | `"TRADE_EXECUTED"`, `"TRADE_REJECTED"`, `"TRADE_SIMULATED"` |
| `mode` | string | Modo operativo del sistema | `"scan"`, `"dry-run"`, `"loop"`, `"scalp"` |
| `market_data_snapshot` | object | Datos de mercado, liquidez y griegas | 9 claves requeridas |
| `agent_proposal` | object | Parámetros del trade propuesto por el agente | 6 claves requeridas |
| `risk_verdict` | object | Dictamen del RiskEngine determinista | 6 claves requeridas |
| `execution_result` | object | Resultado de la orden en el broker o simulación | 6 claves requeridas |

### 2. Conformidad Multi-Activo con Draft-07
- **Acciones y ETFs (`asset_class: "equity"`)**:
  - Emplea indicadores sintéticos y neutros para cumplir exhaustivamente el esquema: `target_option_type="EQUITY"`, `option_symbol=ticker`, `dte=0`, `delta="1.00"`.
  - Multiplicador de $1$: `trade_cost` calculado como $P_{\text{ask}} \times Q$.
- **Opciones (`asset_class: "option"`)**:
  - Incorpora simbología OCC, griegas Black-Scholes ($\Delta, \Gamma, \Theta, \nu, \text{IV}$), horizonte DTE y multiplicador $100$.

### 3. Modos Operativos Soportados
- `"scan"`: Escaneo único de swing sobre opciones o acciones.
- `"dry-run"`: Simulación local sin órdenes al broker (`event_type: TRADE_SIMULATED`).
- `"loop"`: Operación continua con intervalos regulares.
- `"scalp"`: Operación de alta frecuencia con barras de 1Min/5Min o `--quick-trade`.
