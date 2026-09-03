# Scalping, Quick-Trade Mode & Web Verification / Modo Scalping, Quick-Trade y Verificación Web

[English](#english) | [Español](#español)

---

<a name="english"></a>
## English Documentation

### Overview
The Scalping and Quick-Trade architecture (`src/main.py`, `src/execution/alpaca_executor.py`, `src/risk/risk_engine.py`) fulfills Hackathon Requirement R3. It enables high-frequency trading cycles and immediate web-verifiable trade execution on the Alpaca Paper Trading dashboard (`https://app.alpaca.markets`), overcoming US options market session limitations through deterministic equity execution and fallback.

### 1. Quick-Trade Deterministic Verification Mode (`--quick-trade`)
The `--quick-trade` command generates an immediate, deterministic 1-share equity order (e.g. for `SPY` or `AAPL`), strictly validates it through the deterministic `RiskEngine` guardrail (5% portfolio risk rule), and submits it to Alpaca Paper Trading.

#### Running Quick-Trade:
```bash
# Execute real quick-trade against Alpaca Paper Trading
python src/main.py --quick-trade

# Execute quick-trade with simulation (zero broker calls)
python src/main.py --quick-trade --mode dry-run

# Specify custom ticker and asset type
python src/main.py --quick-trade --tickers AAPL --asset-type equity
```

#### Console Output Format:
Upon approval and execution, the console outputs:
```
[QUICK-TRADE SUCCESS] Order ID: 4a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d | Symbol: SPY | Qty: 1 | Status: filled
Dashboard Web: https://app.alpaca.markets
```
The operator can open `https://app.alpaca.markets` and immediately verify the order by its unique `Order ID`, `Symbol`, and `Qty`.

### 2. High-Frequency Scalp Mode (`--mode scalp`)
Scalp mode is designed for rapid trade execution based on micro-momentum indicators calculated across 1-minute or 5-minute bars.

#### Running Scalp Mode:
```bash
# 1-minute bars scalp scan
python src/main.py --mode scalp --timeframe 1Min --tickers SPY

# 5-minute bars scalp scan
python src/main.py --mode scalp --timeframe 5Min --tickers AAPL,MSFT,SPY

# Scalp mode simulation in dry-run
python src/main.py --mode scalp --mode dry-run --timeframe 1Min

# Continuous scalp loop with 30-second intervals
python src/main.py --mode scalp --timeframe 1Min --continuous --interval 30
```

### 3. Multi-Asset Execution & Equity Fallback (`fallback_to_equity`)
US options markets are strictly restricted to regular trading hours (9:30 AM – 4:00 PM Eastern Time). Outside these hours, or during illiquid market regimes:
1. **The Challenge**: Sending option orders when the options market is closed or when contracts have zero bid/ask quotes causes broker rejection.
2. **The Solution (`fallback_to_equity`)**: If options markets are closed (`clock_info.is_open == False`) or if option chains return no qualifying liquid contracts, the system automatically triggers a fallback to the underlying equity (e.g. SPY, AAPL).
3. **24/7 Web Verifiability**: Alpaca Paper Trading accepts equity orders 24/7 (queuing orders outside market hours with an immediate valid `Order ID`). This guarantees that user evaluation and hackathon judges can verify trade generation and broker transmission at any time of day or night.
4. **Differentiated Multiplier**:
   - Equities: $\text{Trade Cost} = P_{\text{ask}} \times 1 \times Q$
   - Options: $\text{Trade Cost} = P_{\text{ask}} \times 100 \times Q$

### 4. Deterministic Pre-Trade Risk Filtering
Every trade proposal—whether initiated by `--quick-trade`, `--mode scalp`, or `--mode scan`—must pass through `RiskEngine.evaluate_proposal()`. If an equity proposal violates:
- The 5% single-trade portfolio limit ($P_{\text{ask}} \times 1 \times Q > V_{\text{portfolio}} \times 0.05$)
- Effective cash or buying power budget
- Bid-ask spread caps (relative spread $> 5.00\%$ or absolute spread $> \$0.50$)
- Crossed quotes ($P_{\text{ask}} < P_{\text{bid}}$) or non-positive quotes

Execution is immediately blocked with zero broker API calls, and the incident is recorded in `logs/trades.jsonl` as `TRADE_REJECTED`.

---

<a name="español"></a>
## Documentación en Español

### Descripción General
La arquitectura de Scalping y Modo Quick-Trade (`src/main.py`, `src/execution/alpaca_executor.py`, `src/risk/risk_engine.py`) cumple el Requisito R3 del Hackathon. Permite ciclos de trading de alta frecuencia y ejecución de órdenes inmediatamente verificables en el dashboard web de Alpaca Paper Trading (`https://app.alpaca.markets`), superando las limitaciones horarias del mercado de opciones estadounidense mediante ejecución determinista de acciones y fallback automático.

### 1. Modo de Verificación Determinista Quick-Trade (`--quick-trade`)
El comando `--quick-trade` genera una orden determinista inmediata de 1 acción (ej. de `SPY` o `AAPL`), la valida estrictamente a través del guardarraíl determinista del `RiskEngine` (regla del 5% de la cartera) y la transmite a Alpaca Paper Trading.

#### Ejecución de Quick-Trade:
```bash
# Ejecución real de quick-trade en Alpaca Paper Trading
python src/main.py --quick-trade

# Ejecución de quick-trade en simulación local (sin llamadas al broker)
python src/main.py --quick-trade --mode dry-run

# Especificar ticker personalizado y tipo de activo
python src/main.py --quick-trade --tickers AAPL --asset-type equity
```

#### Formato de Salida en Consola:
Tras ser aprobada y emitida, la consola muestra:
```
[QUICK-TRADE SUCCESS] Order ID: 4a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d | Symbol: SPY | Qty: 1 | Status: filled
Dashboard Web: https://app.alpaca.markets
```
El operador puede ingresar a `https://app.alpaca.markets` y corroborar en tiempo real la existencia de la orden utilizando su `Order ID`, `Symbol` y `Qty`.

### 2. Modo Scalping de Alta Frecuencia (`--mode scalp`)
El modo scalp opera con ciclos rápidos basados en micro-momentum calculados sobre barras de 1 minuto o 5 minutos.

#### Ejecución de Modo Scalp:
```bash
# Escaneo scalp con velas de 1 minuto
python src/main.py --mode scalp --timeframe 1Min --tickers SPY

# Escaneo scalp con velas de 5 minutos
python src/main.py --mode scalp --timeframe 5Min --tickers AAPL,MSFT,SPY

# Simulación de scalp en modo dry-run
python src/main.py --mode scalp --mode dry-run --timeframe 1Min

# Bucle continuo de scalp con intervalo de 30 segundos
python src/main.py --mode scalp --timeframe 1Min --continuous --interval 30
```

### 3. Ejecución Multi-Activo y Fallback a Acciones (`fallback_to_equity`)
El mercado de opciones en Estados Unidos opera exclusivamente en horario regular (9:30 AM – 4:00 PM Hora del Este). Fuera de este horario, o en regímenes de baja liquidez:
1. **El Desafío**: Enviar órdenes de opciones con el mercado cerrado o con cotizaciones ilíquidas provoca el rechazo por parte del broker.
2. **La Solución (`fallback_to_equity`)**: Si el mercado de opciones está cerrado (`clock_info.is_open == False`) o la cadena de opciones no ofrece contratos líquidos válidos, el sistema conmuta automáticamente hacia acciones del subyacente (ej. SPY o AAPL).
3. **Verificación Web 24/7**: Alpaca Paper Trading acepta órdenes de acciones 24/7 (encolándolas fuera de horario con un `Order ID` válido e inmediato). Esto asegura que los evaluadores y jueces del hackathon puedan verificar la emisión de órdenes en el dashboard web en cualquier momento del día o de la noche.
4. **Multiplicador Diferenciado**:
   - Acciones: $\text{Costo del Trade} = P_{\text{ask}} \times 1 \times Q$
   - Opciones: $\text{Costo del Trade} = P_{\text{ask}} \times 100 \times Q$

### 4. Filtrado Determinista Pre-Trade del RiskEngine
Toda propuesta de trading—provenga de `--quick-trade`, `--mode scalp` o `--mode scan`—debe ser evaluada por `RiskEngine.evaluate_proposal()`. Si una propuesta de acciones infringe:
- El límite del 5% del valor de la cartera ($P_{\text{ask}} \times 1 \times Q > V_{\text{portfolio}} \times 0.05$)
- El presupuesto efectivo de Cash o Buying Power
- Los límites de spread bid-ask (spread relativo $> 5.00\%$ o absoluto $> \$0.50$)
- Cotizaciones cruzadas ($P_{\text{ask}} < P_{\text{bid}}$) o no positivas

La ejecución queda físicamente bloqueada sin llamadas al broker, registrándose en `logs/trades.jsonl` con veredicto `TRADE_REJECTED`.
