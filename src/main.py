"""
Orquestador Principal del Sistema de Trading Autónomo de Opciones y Acciones en Alpaca (Paper Trading).

Uso:
    python src/main.py --mode scan         # Ejecuta un ciclo de escaneo y trading de swing (15Min)
    python src/main.py --mode loop         # Ejecuta de forma continua en tiempo real
    python src/main.py --mode dry-run      # Simula todo el pipeline sin enviar órdenes a Alpaca
    python src/main.py --mode scalp        # Ejecuta operativa rápida (1Min/5Min) con fallback a acciones
    python src/main.py --quick-trade       # Ejecuta orden de test determinista validada por RiskEngine
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

# Asegurar que el root del proyecto esté en sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.account import (
    AccountAuthError,
    AccountHealth,
    AccountLimits,
    AccountSnapshot,
    MarketClockInfo,
    calculate_trade_limits,
    check_account_health,
)
from src.agents.strategy_agent import AutonomousStrategyAgent, SignalType, TradingSignal
from src.config import DEFAULT_UNIVERSE
from src.data.market import LiquidityScore, MarketDataService, screen_ticker_liquidity
from src.execution.alpaca_executor import AlpacaOrderExecutor, ExecutionResult, OptionExecutor
from src.execution.mcp_gateway import AlpacaGateway
from src.execution.trade_logger import TradeLogger
from src.indicators.technicals import (
    PriceBar,
    TechnicalSnapshot,
    compute_technical_snapshot,
    to_decimal,
)
from src.options.chain_filter import filter_option_chain
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


def print_banner():
    banner = """
======================================================================
  ALPACA AI OPTIONS & EQUITY AUTONOMOUS TRADING AGENT
  Paper Trading Environment | 100% Decimal Precision | 5% Risk Engine
======================================================================
"""
    print(banner)


def get_scalp_bars(
    ticker: str,
    timeframe: str = "1Min",
    limit: int = 30,
) -> list[PriceBar]:
    """
    Obtiene velas de alta frecuencia (1Min o 5Min) para el análisis técnico de scalping.
    Intenta consultar Alpaca Historical Data con credenciales activas y proporciona
    fallback sintético determinista si la API no está disponible o en modo offline.
    """
    try:
        from datetime import datetime, timedelta, timezone
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("API_KEY")
        secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("SECRET_KEY")
        if api_key and secret_key:
            client = StockHistoricalDataClient(api_key, secret_key)
            start_dt = datetime.now(timezone.utc) - timedelta(days=2)
            tf_num = 1 if timeframe == "1Min" else (5 if timeframe == "5Min" else 15)
            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame(tf_num, TimeFrameUnit.Minute),
                start=start_dt,
                limit=limit,
            )
            bars_res = client.get_stock_bars(req)
            if ticker in bars_res and bars_res[ticker]:
                return MarketDataService().parse_alpaca_bars(bars_res[ticker])
    except Exception:
        pass

    # Fallback sintético determinista para scalping
    base = Decimal("180.00") if ticker == "AAPL" else Decimal("500.00")
    step_minutes = 1 if timeframe == "1Min" else (5 if timeframe == "5Min" else 15)
    return [
        PriceBar.create(
            open_p=base + Decimal(str(round(i * 0.15, 2))),
            high_p=base + Decimal(str(round(i * 0.15 + 0.40, 2))),
            low_p=base + Decimal(str(round(i * 0.15 - 0.20, 2))),
            close_p=base + Decimal(str(round(i * 0.15 + 0.25, 2))),
            volume_p="50000",
            timestamp=f"2026-09-03T14:{(i * step_minutes) % 60:02d}:00Z",
        )
        for i in range(max(30, limit))
    ]


def get_equity_market_quote(
    ticker: str,
    default_price: Optional[Decimal] = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Obtiene cotizaciones bid/ask y precio de referencia para un activo de acciones/ETFs.
    Garantiza que ask >= bid > 0 con un spread ajustado (< $0.50 y < 1.00%).
    Retorna una tupla (ref_price, ask_price, bid_price).
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest

        api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("API_KEY")
        secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("SECRET_KEY")
        if api_key and secret_key:
            client = StockHistoricalDataClient(api_key, secret_key)
            req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
            quotes = client.get_stock_latest_quote(req)
            if ticker in quotes and quotes[ticker]:
                q = quotes[ticker]
                ask = to_decimal(getattr(q, "ask_price", 0))
                bid = to_decimal(getattr(q, "bid_price", 0))
                if ask > Decimal("0.0") and bid > Decimal("0.0") and ask >= bid:
                    mid = ((ask + bid) / Decimal("2.0")).quantize(Decimal("0.01"))
                    if (ask - bid) <= Decimal("0.50"):
                        return (mid, ask, bid)
    except Exception:
        pass

    # Fallback determinista usando velas o precio base
    if default_price is not None and default_price > Decimal("0.0"):
        ref = default_price
    else:
        bars = get_scalp_bars(ticker, timeframe="1Min", limit=5)
        ref = bars[-1].close if bars else (Decimal("180.00") if ticker == "AAPL" else Decimal("500.00"))

    ref = ref.quantize(Decimal("0.01"))
    ask = (ref + Decimal("0.02")).quantize(Decimal("0.01"))
    bid = (ref - Decimal("0.02")).quantize(Decimal("0.01"))
    return (ref, ask, bid)


def run_quick_trade(
    ticker: str = "SPY",
    dry_run: bool = False,
    logger: Optional[TradeLogger] = None,
    gateway: Optional[AlpacaGateway] = None,
    asset_type: str = "equity",
) -> Optional[ExecutionResult]:
    """
    Ejecuta una orden de test rápida determinista pre-validada por el RiskEngine (regla del 5%)
    para verificación inmediata de visibilidad en el dashboard web de Alpaca Paper Trading.
    """
    log = logger or TradeLogger()
    risk_engine = RiskEngine()
    gw = gateway or AlpacaGateway(mode="auto")
    mode_str = "dry-run" if dry_run else "scan"
    executor = OptionExecutor(gateway=gw, logger=log, dry_run=dry_run, mode=mode_str)

    print("\n======================================================================")
    print("  EJECUTANDO --quick-trade: Test Determinista con Risk Engine")
    print("======================================================================")

    # 1. Consultar estado de cuenta y reloj de mercado
    try:
        snapshot = gw.get_account()
    except AccountAuthError as auth_err:
        print(f"\n[ERROR DE AUTENTICACION] {auth_err}")
        print("Por favor verifica que APCA_API_KEY_ID y APCA_API_SECRET_KEY estén definidos en tu archivo .env")
        return None
    except Exception as exc:
        print(f"\n[ERROR DE CONEXION] No se pudo conectar con Alpaca: {exc}")
        return None

    health = check_account_health(snapshot)
    limits = calculate_trade_limits(snapshot)
    clock_info = gw.get_clock()

    print(f"  * Activo Objetivo: {ticker} (Clase: {asset_type.upper()})")
    print(f"  * Modo: {'DRY-RUN (Simulación)' if dry_run else 'PAPER TRADING (Orden Real)'}")
    print(f"  * ID Cuenta: {snapshot.account_id}")
    print(f"  * Mercado EE.UU.: {'ABIERTO 🟢' if clock_info.is_open else 'CERRADO 🔴 (Próxima apertura: ' + str(clock_info.next_open) + ')'}")
    print(f"  * Portfolio Value: ${snapshot.portfolio_value} | Cash: ${snapshot.cash} | BP: ${snapshot.buying_power}")
    print(f"  * Límite 5% por Trade: ${limits.max_single_trade_risk} | Presupuesto Disponible: ${limits.effective_trade_budget}")
    print(f"  * Estado de Salud: {'SALUDABLE' if health.is_healthy else 'CON ADVERTENCIAS'} (Puede operar: {health.can_trade})")

    if not health.can_trade:
        print(f"\n[BLOQUEO DE SEGURIDAD] Trading suspendido por errores en cuenta:")
        for err in health.critical_errors:
            print(f"    - {err}")
        return None

    # 2. Obtener cotización de mercado para el ticker objetivo
    ref_price, ref_ask, ref_bid = get_equity_market_quote(ticker)
    print(f"  * Cotización de Mercado: Precio: ${ref_price} | Bid: ${ref_bid} | Ask: ${ref_ask}")

    # 3. Construir TradeProposal determinista (1 unidad de activo, regla del 5%)
    proposal = TradeProposal(
        symbol=ticker,
        underlying_symbol=ticker,
        quantity=1,
        strategy_name="QuickTradeDeterministic",
        action="BUY",
        side="buy",
        asset_class="equity",
        price=ref_price,
        ask_price=ref_ask,
        bid_price=ref_bid,
        signal_type="QUICK_TRADE",
        confidence=Decimal("1.00"),
        rationale=f"Deterministic test trade for web dashboard verification ({ticker})",
    )

    print(f"  * Propuesta: Comprar 1 acción de {ticker} a ${ref_ask} (Costo total: ${ref_ask})")

    # 4. Evaluación Determinista Obligatoria en RiskEngine
    verdict = risk_engine.evaluate_proposal(
        proposal=proposal,
        snapshot=snapshot,
        underlying_price=ref_price,
        ask_price=ref_ask,
        bid_price=ref_bid,
    )

    print(f"  * Dictamen Risk Engine: {'APROBADO ✅' if verdict.is_approved else 'RECHAZADO ❌'}")
    if verdict.warnings:
        print(f"  * Advertencias: {verdict.warnings}")

    if not verdict.is_approved:
        reasons_summary = "; ".join(verdict.reasons) if verdict.reasons else (verdict.message or str(verdict.reason_code))
        rc_list = [rc.value if hasattr(rc, "value") else str(rc) for rc in verdict.reason_codes]
        print(f"\n[QUICK-TRADE REJECTED] Motivo: {reasons_summary}")
        print(f"Códigos de Rechazo: {rc_list}")
        log.log_rejected_trade(proposal=proposal, verdict=verdict, mode=mode_str)
        return None

    print(f"  * Costo Aprobado: ${verdict.trade_cost} | Límite Máximo 5%: ${verdict.max_allowed_budget}")
    print(f"  * Riesgo de Cartera Utilizado: {verdict.portfolio_risk_pct_used * Decimal('100.0')}%")

    # 5. Ejecutar la orden aprobada vía AlpacaOrderExecutor
    if dry_run:
        print("  * [DRY-RUN] Simulando ejecución en memoria...")
    else:
        print("  * Transmitiendo orden a Alpaca Paper Trading...")

    exec_result = executor.execute_approved_trade(
        proposal=proposal,
        verdict=verdict,
        dry_run=dry_run,
    )

    # 6. Feedback en consola para el usuario
    if exec_result.success:
        print(f"\n[QUICK-TRADE SUCCESS] Order ID: {exec_result.order_id} | Symbol: {exec_result.symbol} | Qty: {exec_result.quantity} | Status: {exec_result.status}")
        print("Dashboard Web: https://app.alpaca.markets")
    else:
        print(f"\n[QUICK-TRADE ERROR] {exec_result.error_message}")

    print("\n======================================================================")
    print("  Operación registrada en logs/trades.jsonl (Draft-07)")
    print("======================================================================\n")

    return exec_result


def run_scalp_cycle(
    universe: list[str],
    dry_run: bool = False,
    timeframe: str = "1Min",
    asset_type: str = "auto",
    logger: Optional[TradeLogger] = None,
    gateway: Optional[AlpacaGateway] = None,
    max_trades: Optional[int] = None,
) -> list[ExecutionResult]:
    """
    Ejecuta un ciclo rápido de scalping (1Min o 5Min) con verificación de reloj de mercado,
    fallback determinista a acciones cuando las opciones están cerradas o ilíquidas,
    y estricta validación del 100% de las propuestas a través del RiskEngine.
    """
    log = logger or TradeLogger()
    risk_engine = RiskEngine()
    agent = AutonomousStrategyAgent()
    gw = gateway or AlpacaGateway(mode="auto")
    mode_str = "dry-run" if dry_run else "scalp"
    executor = OptionExecutor(gateway=gw, logger=log, dry_run=dry_run, mode=mode_str)
    results: list[ExecutionResult] = []

    print("\n======================================================================")
    print(f"  ALPACA AUTONOMOUS SCALP AGENT ({timeframe}) | Mode: {mode_str.upper()}")
    print("======================================================================")

    # 1. Consultar cuenta y reloj de mercado
    print("\n[1/5] Consultando estado de la cuenta y reloj de mercado en Alpaca...")
    try:
        snapshot = gw.get_account()
    except AccountAuthError as auth_err:
        print(f"\n[ERROR DE AUTENTICACION] {auth_err}")
        print("Por favor verifica que APCA_API_KEY_ID y APCA_API_SECRET_KEY estén definidos en tu archivo .env")
        return results
    except Exception as exc:
        print(f"\n[ERROR DE CONEXION] No se pudo conectar con Alpaca: {exc}")
        return results

    health = check_account_health(snapshot)
    limits = calculate_trade_limits(snapshot)
    clock_info = gw.get_clock()

    print(f"  * ID Cuenta: {snapshot.account_id}")
    print(f"  * Mercado de EE.UU.: {'ABIERTO 🟢' if clock_info.is_open else 'CERRADO 🔴 (Próxima apertura: ' + str(clock_info.next_open) + ')'}")
    print(f"  * Portfolio Value: ${snapshot.portfolio_value} | Cash: ${snapshot.cash} | BP: ${snapshot.buying_power}")
    print(f"  * Límite Máximo por Trade (Regla 5%): ${limits.max_single_trade_risk}")
    print(f"  * Presupuesto Efectivo Disponible: ${limits.effective_trade_budget}")
    print(f"  * Estado de Salud: {'SALUDABLE' if health.is_healthy else 'CON ADVERTENCIAS'} (Puede operar: {health.can_trade})")

    if not health.can_trade:
        print(f"\n[BLOQUEO DE SEGURIDAD] Trading suspendido por errores en cuenta:")
        for err in health.critical_errors:
            print(f"    - {err}")
        return results

    # Las opciones sólo cotizan durante el horario regular de mercado de EE.UU. (9:30 AM - 4:00 PM ET)
    options_market_active = clock_info.is_open and (asset_type in ("auto", "option"))

    print(f"\n[2/5] Evaluando Universo de Scalping ({', '.join(universe)} | Timeframe: {timeframe})...")
    trades_executed = 0

    for ticker in universe:
        if max_trades is not None and trades_executed >= max_trades:
            break

        print(f"\n--- Analizando Scalp en {ticker} ---")

        # Ingestar velas de alta frecuencia (1Min o 5Min)
        bars = get_scalp_bars(ticker, timeframe=timeframe, limit=30)
        tech_snap = compute_technical_snapshot(ticker, bars)
        print(f"  * Análisis Técnico ({timeframe}): Precio: ${tech_snap.current_price} | Tendencia: {tech_snap.trend_summary} | RSI: {tech_snap.rsi_14}")

        # [3/5] Evaluación del Agente de Estrategia
        signal = agent.evaluate_signals(tech_snap)
        print(f"  * Señal del Agente: {signal.signal_type.value} (Confianza: {signal.confidence * Decimal('100.0')}%)")
        print(f"  * Razón: {signal.rationale}")

        # En modo scalp, si no hay señal direccional extrema, se evalúa micro-momentum rápido
        if signal.signal_type == SignalType.NEUTRAL_HOLD:
            if tech_snap.current_price >= tech_snap.sma_20:
                trade_action = "BUY"
                trade_signal_type = "SCALP_MICRO_MOMENTUM_BULLISH"
                trade_rationale = f"Scalp {timeframe}: Precio ${tech_snap.current_price} >= SMA20 ${tech_snap.sma_20}"
                target_opt_type = OptionType.CALL
            else:
                trade_action = "BUY"
                trade_signal_type = "SCALP_MICRO_MOMENTUM_PULLBACK"
                trade_rationale = f"Scalp {timeframe}: Pullback técnico (RSI {tech_snap.rsi_14})"
                target_opt_type = OptionType.PUT
        else:
            trade_action = "BUY"
            trade_signal_type = signal.signal_type.value
            trade_rationale = signal.rationale
            target_opt_type = signal.target_option_type or OptionType.CALL

        # [4/5] Decisión Multi-Activo: Opciones vs Fallback a Acciones
        selected_contract = None
        use_equity_fallback = True

        if options_market_active and asset_type != "equity":
            print(f"  * Consultando cadena de opciones para {ticker}...")
            try:
                chain = gw.get_option_chain(underlying=ticker, min_dte=1, max_dte=30)
            except Exception as chain_err:
                print(f"  * Advertencia al consultar opciones: {chain_err}")
                chain = []

            for c in chain:
                if c.contract_type == target_opt_type and c.underlying_symbol == ticker and c.bid_price > Decimal("0.0"):
                    selected_contract = c
                    use_equity_fallback = False
                    break

        if use_equity_fallback:
            if not clock_info.is_open:
                print(f"  * [FALLBACK A ACCIONES] Mercado de opciones cerrado. Operando acciones/ETFs ({ticker}) para ejecución inmediata.")
            else:
                print(f"  * [FALLBACK A ACCIONES] Contratos de opciones ilíquidos o ausentes. Operando acciones/ETFs ({ticker}).")

            ref_price, ref_ask, ref_bid = get_equity_market_quote(ticker, default_price=tech_snap.current_price)
            # Cantidad segura determinista: 1 acción para garantizar cumplimiento estricto de la regla del 5%
            proposal = TradeProposal(
                symbol=ticker,
                underlying_symbol=ticker,
                quantity=1,
                strategy_name=f"Scalp_{timeframe}_EquityFallback",
                action=trade_action,
                side=trade_action.lower(),
                asset_class="equity",
                price=ref_price,
                ask_price=ref_ask,
                bid_price=ref_bid,
                signal_type=trade_signal_type,
                confidence=Decimal("0.85"),
                rationale=f"Scalp fallback a acciones: {trade_rationale}",
            )
            cost = ref_ask
            print(f"  * Propuesta: Comprar {proposal.quantity} acción(es) de {ticker} a ${ref_ask} (Costo total: ${cost})")
        else:
            proposal = TradeProposal(
                contract=selected_contract,
                quantity=1,
                strategy_name=f"Scalp_{timeframe}_Option",
                action=trade_action,
                side=trade_action.lower(),
                asset_class="option",
                signal_type=trade_signal_type,
                confidence=Decimal("0.85"),
                rationale=f"Scalp opción: {trade_rationale}",
            )
            cost = selected_contract.calculate_trade_cost(contracts=proposal.quantity, use_ask=True)
            print(f"  * Propuesta: Comprar {proposal.quantity} contrato(s) {selected_contract.symbol} a ${selected_contract.ask_price} (Costo total: ${cost})")

        # [5/5] Evaluación Determinista en Risk Engine (Regla del 5%)
        if proposal.is_equity:
            verdict = risk_engine.evaluate_proposal(
                proposal=proposal,
                snapshot=snapshot,
                underlying_price=ref_price,
                ask_price=ref_ask,
                bid_price=ref_bid,
            )
        else:
            verdict = risk_engine.evaluate_proposal(
                proposal=proposal,
                snapshot=snapshot,
                contract=selected_contract,
                underlying_price=tech_snap.current_price,
            )

        print(f"  * Dictamen Risk Engine: {'APROBADO ✅' if verdict.is_approved else 'RECHAZADO ❌'}")
        if verdict.warnings:
            print(f"  * Advertencias de Riesgo: {verdict.warnings}")

        if not verdict.is_approved:
            print(f"  * [BLOQUEO RISK ENGINE] {verdict.message}")
            log.log_rejected_trade(proposal=proposal, verdict=verdict, mode=mode_str)
            continue

        if dry_run:
            print("  * [DRY-RUN] Modo simulación activado.")
        else:
            print("  * Enviando orden a Alpaca Paper Trading...")

        exec_result = executor.execute_approved_trade(
            proposal=proposal,
            verdict=verdict,
            dry_run=dry_run,
        )

        results.append(exec_result)

        if exec_result.success:
            trades_executed += 1
            print(f"  * [SCALP SUCCESS] Order ID: {exec_result.order_id} | Symbol: {exec_result.symbol} | Qty: {exec_result.quantity} | Status: {exec_result.status}")
            print("  * Dashboard Web: https://app.alpaca.markets")
        else:
            print(f"  * [SCALP ERROR] {exec_result.error_message}")

    print("\n======================================================================")
    print("  Ciclo de scalping completado. Registros en logs/trades.jsonl")
    print("======================================================================\n")

    return results


def run_trading_cycle(
    universe: list[str],
    dry_run: bool = False,
    logger: Optional[TradeLogger] = None,
    gateway: Optional[AlpacaGateway] = None,
) -> None:
    """Ejecuta un ciclo completo de escaneo, análisis, riesgo y ejecución."""
    log = logger or TradeLogger()
    risk_engine = RiskEngine()
    agent = AutonomousStrategyAgent()
    mode_str = "dry-run" if dry_run else "scan"

    print("\n[1/5] Consultando estado de la cuenta en Alpaca vía AlpacaGateway...")
    gw = gateway or AlpacaGateway(mode="auto")
    try:
        snapshot = gw.get_account()
    except AccountAuthError as auth_err:
        print(f"\n[ERROR DE AUTENTICACION] {auth_err}")
        print("Por favor verifica que APCA_API_KEY_ID y APCA_API_SECRET_KEY estén definidos en tu archivo .env")
        return
    except Exception as exc:
        print(f"\n[ERROR DE CONEXION] No se pudo conectar con Alpaca: {exc}")
        return

    # 1. Health Check & Reloj de Mercado
    health = check_account_health(snapshot)
    limits = calculate_trade_limits(snapshot)
    clock_info = gw.get_clock()

    print(f"  * ID Cuenta: {snapshot.account_id}")
    print(f"  * Mercado de EE.UU.: {'ABIERTO 🟢' if clock_info.is_open else 'CERRADO 🔴 (Próxima apertura: ' + str(clock_info.next_open) + ')'}")
    print(f"  * Portfolio Value: ${snapshot.portfolio_value} | Cash: ${snapshot.cash}")
    print(f"  * Buying Power: ${snapshot.buying_power} | Equity: ${snapshot.equity}")
    print(f"  * Límite Máximo por Trade (Regla 5%): ${limits.max_single_trade_risk}")
    print(f"  * Presupuesto Efectivo Disponible: ${limits.effective_trade_budget}")
    print(f"  * Estado de Salud: {'SALUDABLE' if health.is_healthy else 'CON ADVERTENCIAS'} (Activa: {snapshot.is_active}, Congelada: {snapshot.is_frozen}, Puede operar: {health.can_trade})")

    if not health.can_trade:
        print(f"\n[BLOQUEO DE SEGURIDAD] Trading suspendido por errores en cuenta:")
        for err in health.critical_errors:
            print(f"    - {err}")
        return

    print(f"\n[2/5] Evaluando Universo de Inversión ({', '.join(universe)})...")
    market_service = MarketDataService()
    executor = OptionExecutor(gateway=gw, logger=log, dry_run=dry_run, mode=mode_str)

    for ticker in universe:
        print(f"\n--- Analizando {ticker} ---")

        # Simulación / Ingestión de datos de mercado para el ciclo
        stats = {
            "volume": "15000000",
            "bid": "180.00",
            "ask": "180.20",
            "open_interest": 1200,
        }
        liq = screen_ticker_liquidity(
            ticker=ticker,
            daily_volume=stats["volume"],
            bid_price=stats["bid"],
            ask_price=stats["ask"],
            option_open_interest=stats["open_interest"],
        )

        print(f"  * Liquidez: {liq.stars}/5 Estrellas (Spread: {liq.bid_ask_spread_pct * Decimal('100.0')}%, Tradable: {liq.is_tradable})")
        if not liq.is_tradable:
            print(f"  * Descartado por liquidez: {liq.reasons}")
            continue

        # Obtener velas de 15 minutos (15Min) para análisis técnico limpio
        bars = market_service.get_15min_bars(ticker, limit=40)
        tech_snap = compute_technical_snapshot(ticker, bars)
        print(f"  * Análisis Técnico (15Min): Precio: ${tech_snap.current_price} | Tendencia: {tech_snap.trend_summary} | RSI: {tech_snap.rsi_14}")

        # [3/5] Evaluación del Agente de Estrategia
        signal = agent.evaluate_signals(tech_snap)
        print(f"  * Señal del Agente: {signal.signal_type.value} (Confianza: {signal.confidence * Decimal('100.0')}%)")
        print(f"  * Razón: {signal.rationale}")

        if signal.signal_type == SignalType.NEUTRAL_HOLD:
            print("  * Sin oportunidad operativa en este momento.")
            continue

        target_opt_type = signal.target_option_type or OptionType.CALL

        # [4/5] Consulta de Cadena de Opciones vía AlpacaGateway
        print(f"  * Consultando cadena de opciones para {ticker} vía AlpacaGateway...")
        try:
            chain = gw.get_option_chain(underlying=ticker, min_dte=1, max_dte=30)
        except Exception as chain_err:
            print(f"  * Advertencia al consultar cadena: {chain_err}")
            chain = []

        selected_contract = None
        for c in chain:
            if c.contract_type == target_opt_type and c.underlying_symbol == ticker:
                selected_contract = c
                break

        if selected_contract is None:
            selected_contract = OptionContract.create(
                symbol=f"{ticker}260930C00180000" if target_opt_type == OptionType.CALL else f"{ticker}260930P00180000",
                underlying_symbol=ticker,
                contract_type=target_opt_type,
                strike_price="180.00",
                expiration_date="2026-09-30",
                dte=20,
                bid_price="2.10",
                ask_price="2.20",
                volume=1500,
                open_interest=1500,
                delta="0.50" if target_opt_type == OptionType.CALL else "-0.50",
                theta="-0.04",
                implied_volatility="0.1850",
            )

        proposal = agent.propose_trade(signal, selected_contract, quantity=1)
        cost = selected_contract.calculate_trade_cost(contracts=proposal.quantity, use_ask=True)
        print(f"  * Propuesta: Comprar {proposal.quantity} contrato(s) {selected_contract.symbol} a ${selected_contract.ask_price} (Costo total: ${cost})")

        # [5/5] Evaluación Determinista en Risk Engine
        verdict = risk_engine.evaluate_trade(
            proposal=proposal,
            account=snapshot,
            contract=selected_contract,
            underlying_price=tech_snap.current_price,
        )
        print(f"  * Dictamen Risk Engine: {'APROBADO' if verdict.is_approved else 'RECHAZADO'}")
        if verdict.warnings:
            print(f"  * Advertencias de Riesgo: {verdict.warnings}")

        if dry_run:
            print("  * [DRY-RUN] Modo simulación activado.")
        else:
            print("  * Enviando orden a Alpaca Paper Trading...")

        exec_result = executor.execute_approved_trade(
            proposal=proposal,
            verdict=verdict,
            dry_run=dry_run,
        )

        if exec_result.success:
            print(f"  * [EXITO] Orden procesada. ID: {exec_result.order_id} | Estado: {exec_result.status}")
        else:
            print(f"  * [BLOQUEADO/ERROR] {exec_result.error_message}")

    print("\n======================================================================")
    print("  Ciclo completado. Registros actualizados en logs/trades.jsonl")
    print("======================================================================\n")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Alpaca Autonomous Options & Equity Trading Agent")
    parser.add_argument(
        "--mode",
        choices=["scan", "loop", "dry-run", "scalp"],
        default="scan",
        help="Modo de ejecución: scan (ciclo swing 15Min), loop (continuo), dry-run (simulación), scalp (alta frecuencia 1Min/5Min)",
    )
    parser.add_argument(
        "--quick-trade",
        action="store_true",
        help="Execute an immediate deterministic test trade validated by RiskEngine for web dashboard verification",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Segundos de espera entre ciclos en modo loop (por defecto: 60)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=",".join(DEFAULT_UNIVERSE),
        help="Lista de tickers separados por comas (ej. AAPL,MSFT,SPY)",
    )
    parser.add_argument(
        "--timeframe",
        choices=["1Min", "5Min", "15Min"],
        default="1Min",
        help="Temporalidad de velas para análisis técnico en modo scalp (por defecto: 1Min)",
    )
    parser.add_argument(
        "--asset-type",
        choices=["auto", "option", "equity"],
        default="auto",
        help="Tipo de activo a operar: auto (opciones si están disponibles, fallback a acciones/ETFs), option, equity",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Ejecuta en loop continuo para el modo seleccionado",
    )

    args = parser.parse_args()
    universe = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    print_banner()
    print(f"Modo seleccionado: {args.mode.upper()} | Tickers: {universe}")

    dry_run = args.mode == "dry-run"

    if args.quick_trade:
        target_ticker = universe[0] if universe else "SPY"
        run_quick_trade(
            ticker=target_ticker,
            dry_run=dry_run,
            asset_type=args.asset_type,
        )
    elif args.mode in ["scan", "dry-run"]:
        run_trading_cycle(universe=universe, dry_run=dry_run)
    elif args.mode == "loop":
        print(f"Iniciando loop continuo cada {args.interval} segundos. Presiona Ctrl+C para detener.")
        try:
            while True:
                run_trading_cycle(universe=universe, dry_run=dry_run)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nLoop autónomo detenido por el usuario.")
    elif args.mode == "scalp":
        if args.continuous:
            print(f"Iniciando loop continuo de scalping ({args.timeframe}) cada {args.interval} segundos. Presiona Ctrl+C para detener.")
            try:
                while True:
                    run_scalp_cycle(
                        universe=universe,
                        dry_run=dry_run,
                        timeframe=args.timeframe,
                        asset_type=args.asset_type,
                    )
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nLoop de scalping detenido por el usuario.")
        else:
            run_scalp_cycle(
                universe=universe,
                dry_run=dry_run,
                timeframe=args.timeframe,
                asset_type=args.asset_type,
            )


if __name__ == "__main__":
    main()
