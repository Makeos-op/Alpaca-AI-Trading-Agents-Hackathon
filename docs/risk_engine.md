# Deterministic RiskEngine Guardrail & Mathematical Specification / Especificación Matemática del Motor de Riesgo

[English](#english) | [Español](#español)

---

<a name="english"></a>
## English Documentation

### Overview
The `RiskEngine` (`src/risk/risk_engine.py` & `src/risk/models.py`) fulfills Hackathon Requirement R2 by acting as an infrangible, deterministic pre-trade validation gate. It eliminates LLM hallucinations, sizing overruns, crossed-market execution, and illiquidity risks for both options and equity/ETF assets.

### 1. Multi-Asset Mathematical Formulations

All mathematical operations use `decimal.Decimal` with rounding mode `ROUND_HALF_UP` to prevent floating-point representation drift.

#### 1.1 Trade Cost & Asset Multiplier
$$\text{Multiplier} = \begin{cases} 1 & \text{for equities / stocks / ETFs} \\ 100 & \text{for standard options} \end{cases}$$

$$C_{\text{trade}} = P_{\text{effective}} \times \text{Multiplier} \times Q$$

Where:
- $P_{\text{effective}} = \max(P_{\text{ask}}, P_{\text{limit}})$ (or $P_{\text{ask}}$ for market orders).
- $Q$ is the proposed quantity of shares or option contracts ($Q \ge 1$).

#### 1.2 Infrangible 5% Single-Trade Risk Limit
$$L_{\text{single\_risk}} = \text{quantize}(V_{\text{portfolio}} \times 0.05, 0.01)$$

A trade proposal is strictly rejected if:
$$C_{\text{trade}} > L_{\text{single\_risk}}$$
Reason code: `RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`.

#### 1.3 Effective Buying Power & Cash Clamping
$$B_{\text{effective}} = \max(0.00, \min(L_{\text{single\_risk}}, BP, C_{\text{cash}}))$$

If $C_{\text{trade}} > B_{\text{effective}}$, the order is rejected with:
`RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER` (or `ERR_INSUFFICIENT_CASH`).

#### 1.4 Options Allocation Cap (25%) vs Equity Exemption
- **Options**: Total cumulative options allocation cannot exceed 25% of portfolio equity:
  $$X_{\text{projected}} = X_{\text{current}} + C_{\text{trade}} \le \text{quantize}(V_{\text{portfolio}} \times 0.25, 0.01)$$
  Exceeding this threshold triggers `RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP`.
- **Equities**: Equities and ETFs are exempt from the 25% options-specific exposure cap, as they represent foundational collateral assets rather than derivative leverage.

#### 1.5 Safe Sizing Calculator (`calculate_max_safe_quantity`)
When an oversized trade proposal is submitted, `RiskEngine` deterministically calculates the maximum safe quantity:
- **Equities**:
  $$Q_{\text{max\_safe}} = \left\lfloor \frac{B_{\text{effective}}}{P_{\text{ask}}} \right\rfloor$$
- **Options**:
  $$Q_{\text{max\_safe}} = \left\lfloor \frac{\min(B_{\text{effective}}, B_{\text{remaining\_options\_cap}})}{P_{\text{ask}} \times 100} \right\rfloor$$

This recommended sizing is returned in `verdict.max_safe_quantity` and `verdict.recommended_quantity`.

### 2. Market Microstructure & Liquidity Guardrails

| Metric | Guardrail Condition | Applies To | Rejection Reason Code |
|---|---|---|---|
| **Crossed / Zero Quote** | $P_{\text{bid}} \le 0$, $P_{\text{ask}} \le 0$, or $P_{\text{bid}} \ge P_{\text{ask}}$ | Equities & Options | `ERR_CROSSED_OR_ZERO_QUOTE` |
| **Relative Spread Cap** | $(P_{\text{ask}} - P_{\text{bid}}) / P_{\text{mid}} > 0.0500$ (5.00%) | Equities & Options | `ERR_WIDE_BID_ASK_SPREAD` |
| **Absolute Spread Cap** | $P_{\text{ask}} - P_{\text{bid}} > \$0.50$ | Equities & Options | `ERR_WIDE_BID_ASK_SPREAD` |
| **Underlying Equity Spread** | $(P_{\text{underlying\_ask}} - P_{\text{underlying\_bid}}) / P_{\text{underlying\_mid}} > 0.0100$ | Options Underlying | `ERR_UNDERLYING_SPREAD_EXCEEDS_MAX` |
| **Open Interest Floor** | $\text{OI} < 500$ contracts | Options Only | `ERR_INSUFFICIENT_OPEN_INTEREST` |
| **Volume Floor** | $\text{Volume} < 100$ contracts | Options Only | `ERR_INSUFFICIENT_VOLUME` |

### 3. Greeks & Expiration Horizon Guardrails (Options Only)

Equities safely bypass option-specific derivative checks. For option proposals, the following strict boundaries apply:

| Metric | Guardrail Condition | Rejection Reason Code |
|---|---|---|
| **Expiration Horizon (DTE)** | $\text{DTE} < 1$ (0-DTE pin risk) or $\text{DTE} > 30$ | `ERR_DTE_OUT_OF_BOUNDS` |
| **Call Delta ($\Delta_{\text{call}}$)** | $\Delta_{\text{call}} < 0.30$ or $\Delta_{\text{call}} > 0.70$ | `ERR_DELTA_OUT_OF_BOUNDS` |
| **Put Delta ($\Delta_{\text{put}}$)** | $\Delta_{\text{put}} < -0.70$ or $\Delta_{\text{put}} > -0.30$ | `ERR_DELTA_OUT_OF_BOUNDS` |
| **Daily Theta Decay Rate** | $|\Theta| / P_{\text{ask}} > 0.0500$ (5.00% daily loss) | `ERR_THETA_DECAY_EXCESSIVE` |
| **Absolute Daily Theta Cap** | $|\Theta| > \$0.15$ ($15.00/contract/day) | `ERR_THETA_DECAY_EXCESSIVE` |
| **Implied Volatility (IV)** | $\text{IV} < 0.05$ (5%) or $\text{IV} > 1.00$ (100%) | `ERR_IV_OUT_OF_BOUNDS` |

### 4. Infrangible Pre-Trade Interception Guarantee
1. **Pre-Trade Interception**: In `OptionExecutor.execute_approved_trade()`, the very first check inspects `verdict.is_approved`. If `verdict.is_approved == False`, execution is immediately halted, returning `ExecutionResult(success=False, status="REJECTED")` with zero broker or gateway API calls.
2. **Adversarial Verification**: Mathematically proven via `tests/test_adversarial_risk.py` using `MockHostileBrokerGateway` (which raises an assertion if invoked).

---

<a name="español"></a>
## Documentación en Español

### Descripción General
El `RiskEngine` (`src/risk/risk_engine.py` y `src/risk/models.py`) cumple el Requisito R2 del Hackathon actuando como un guardarraíl pre-trade determinista e infranqueable. Elimina alucinaciones de modelos de lenguaje, excesos de tamaño de posición, ejecuciones con cotizaciones cruzadas y riesgos de iliquidez tanto para opciones como para acciones/ETFs.

### 1. Formulaciones Matemáticas Multi-Activo

Todas las operaciones se ejecutan con `decimal.Decimal` y redondeo `ROUND_HALF_UP`, previniendo errores de precisión en punto flotante.

#### 1.1 Costo del Trade y Multiplicador por Activo
$$\text{Multiplicador} = \begin{cases} 1 & \text{para acciones / ETFs} \\ 100 & \text{para contratos de opciones estándar} \end{cases}$$

$$C_{\text{trade}} = P_{\text{efectivo}} \times \text{Multiplicador} \times Q$$

Donde:
- $P_{\text{efectivo}} = \max(P_{\text{ask}}, P_{\text{limit}})$ (o $P_{\text{ask}}$ en órdenes de mercado).
- $Q$ es la cantidad propuesta de acciones o contratos ($Q \ge 1$).

#### 1.2 Regla Infranqueable del 5% del Portafolio
$$L_{\text{riesgo\_unitario}} = \text{quantize}(V_{\text{cartera}} \times 0.05, 0.01)$$

Toda propuesta es estrictamente rechazada si:
$$C_{\text{trade}} > L_{\text{riesgo\_unitario}}$$
Código de rechazo: `RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT`.

#### 1.3 Límite de Presupuesto Efectivo (Cash y Buying Power)
$$B_{\text{efectivo}} = \max(0.00, \min(L_{\text{riesgo\_unitario}}, BP, C_{\text{efectivo}}))$$

Si $C_{\text{trade}} > B_{\text{efectivo}}$, la orden es bloqueada con:
`RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER` (o `ERR_INSUFFICIENT_CASH`).

#### 1.4 Límite del 25% Acumulado en Opciones vs Exención de Acciones
- **Opciones**: La exposición total acumulada en opciones no puede exceder el 25% del valor de la cartera:
  $$X_{\text{proyectada}} = X_{\text{actual}} + C_{\text{trade}} \le \text{quantize}(V_{\text{cartera}} \times 0.25, 0.01)$$
  Superar este valor genera `RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP`.
- **Acciones**: Las acciones y ETFs están exentos del tope del 25% de derivados, al tratarse de activos de garantía patrimonial base y no de apalancamiento derivado.

#### 1.5 Calculadora de Tamaño Seguro Recomendado (`calculate_max_safe_quantity`)
Cuando una propuesta excede el capital permitido, el `RiskEngine` calcula de forma determinista la cantidad máxima segura:
- **Acciones**:
  $$Q_{\text{seguro}} = \left\lfloor \frac{B_{\text{efectivo}}}{P_{\text{ask}}} \right\rfloor$$
- **Opciones**:
  $$Q_{\text{seguro}} = \left\lfloor \frac{\min(B_{\text{efectivo}}, B_{\text{remanente\_opciones}})}{P_{\text{ask}} \times 100} \right\rfloor$$

El valor se retorna en `verdict.max_safe_quantity` y `verdict.recommended_quantity`.

### 2. Guardarraíles de Microestructura y Liquidez

| Métrica | Condición de Rechazo | Aplica a | Código de Rechazo |
|---|---|---|---|
| **Cotización Cruzada o Nula** | $P_{\text{bid}} \le 0$, $P_{\text{ask}} \le 0$, o $P_{\text{bid}} \ge P_{\text{ask}}$ | Acciones y Opciones | `ERR_CROSSED_OR_ZERO_QUOTE` |
| **Spread Relativo Máximo** | $(P_{\text{ask}} - P_{\text{bid}}) / P_{\text{mid}} > 0.0500$ (5.00%) | Acciones y Opciones | `ERR_WIDE_BID_ASK_SPREAD` |
| **Spread Absoluto Máximo** | $P_{\text{ask}} - P_{\text{bid}} > \$0.50$ | Acciones y Opciones | `ERR_WIDE_BID_ASK_SPREAD` |
| **Spread de Acción Subyacente** | $(P_{\text{suby\_ask}} - P_{\text{suby\_bid}}) / P_{\text{suby\_mid}} > 0.0100$ | Subyacente de Opciones | `ERR_UNDERLYING_SPREAD_EXCEEDS_MAX` |
| **Piso de Interés Abierto** | $\text{OI} < 500$ contratos | Opciones | `ERR_INSUFFICIENT_OPEN_INTEREST` |
| **Piso de Volumen Diario** | $\text{Volumen} < 100$ contratos | Opciones | `ERR_INSUFFICIENT_VOLUME` |

### 3. Filtros de Griegas y Vencimiento (Exclusivo de Opciones)
Las propuestas de acciones omiten los filtros de derivados. Para opciones, rigen:
- **DTE**: $1 \le \text{DTE} \le 30$ (rechaza 0-DTE y vencimientos lejanos).
- **Delta**: $[0.30, 0.70]$ para Calls y $[-0.70, -0.30]$ para Puts.
- **Theta**: Pérdida máxima de valor temporal $\le 5.00\%$ diario o $\$0.15$/día.
- **Volatilidad Implícita (IV)**: Entre $5\%$ y $100\%$.

### 4. Garantía de Intercepción Pre-Trade
- Si `verdict.is_approved == False`, `OptionExecutor.execute_approved_trade()` cancela la operación de forma fulminante sin invocar la API del broker.
- Respaldado por `tests/test_adversarial_risk.py` con `MockHostileBrokerGateway`.
