"""
Orquestador Principal del Sistema de Trading Autónomo de Opciones en Alpaca (Paper Trading).

Uso:
    python src/main.py --mode scan       # Ejecuta un ciclo de escaneo y trading
    python src/main.py --mode loop       # Ejecuta de forma continua en tiempo real
    python src/main.py --mode dry-run    # Simula todo el pipeline sin enviar órdenes a Alpaca
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
    get_account_snapshot,
    get_market_clock,
    get_trading_client,
)
from src.agents.strategy_agent import AutonomousStrategyAgent, SignalType, TradingSignal
from src.config import DEFAULT_UNIVERSE
from src.data.market import LiquidityScore, MarketDataService, screen_ticker_liquidity
from src.execution.alpaca_executor import ExecutionResult, OptionExecutor
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
  ALPACA AI OPTIONS AUTONOMOUS TRADING AGENT
  Paper Trading Environment | 100% Decimal Precision | 5% Risk Engine
======================================================================
"""
    print(banner)


def run_trading_cycle(
    universe: list[str],
    dry_run: bool = False,
    logger: Optional[TradeLogger] = None,
) -> None:
    """Ejecuta un ciclo completo de escaneo, análisis, riesgo y ejecución."""
    log = logger or TradeLogger()
    risk_engine = RiskEngine()
    agent = AutonomousStrategyAgent()

    print("\n[1/5] Consultando estado de la cuenta en Alpaca...")
    try:
        trading_client = get_trading_client()
        snapshot = get_account_snapshot(trading_client)
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
    clock_info = get_market_clock(trading_client)

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

    for ticker in universe:
        print(f"\n--- Analizando {ticker} ---")

        # Simulación / Ingestión de datos de mercado para el ciclo
        # (En producción lee cotizaciones en vivo mediante MarketDataService)
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
        sample_contract = OptionContract.create(
            symbol=f"{ticker}260930C00180000" if signal.target_option_type == OptionType.CALL else f"{ticker}260930P00180000",
            contract_type=signal.target_option_type or OptionType.CALL,
            strike_price="180.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            open_interest=1500,
            delta="0.50" if signal.target_option_type == OptionType.CALL else "-0.50",
            theta="-0.04",
            implied_volatility="0.1850",
        )

        proposal = agent.propose_trade(signal, sample_contract, quantity=1)
        cost = sample_contract.calculate_trade_cost(contracts=proposal.quantity, use_ask=True)
        print(f"  * Propuesta: Comprar {proposal.quantity} contrato(s) {sample_contract.symbol} a ${sample_contract.ask_price} (Costo total: ${cost})")

        # [5/5] Evaluación Determinista en Risk Engine
        verdict = risk_engine.evaluate_trade(proposal, snapshot)
        print(f"  * Dictamen Risk Engine: {'APROBADO' if verdict.is_approved else 'RECHAZADO'}")
        if verdict.warnings:
            print(f"  * Advertencias de Riesgo: {verdict.warnings}")

        if not verdict.is_approved:
            print(f"  * Motivos de Rechazo: {verdict.reasons}")
            log.log_rejected_trade(proposal, verdict)
            continue

        # Ejecución
        if dry_run:
            print(f"  * [DRY-RUN] Simulación exitosa. Orden aprobada pero no enviada a Alpaca.")
            log.log_executed_trade(proposal, verdict, order_id="dry-run-order", fill_price=sample_contract.ask_price, status="SIMULATED")
        else:
            print(f"  * Enviando orden a Alpaca Paper Trading...")
            executor = OptionExecutor(trading_client=trading_client, logger=log)
            exec_result = executor.execute_approved_trade(proposal, verdict)
            if exec_result.success:
                print(f"  * [EXITO] Orden ejecutada en Alpaca. ID: {exec_result.order_id} | Estado: {exec_result.status}")
            else:
                print(f"  * [ERROR] No se pudo ejecutar en Alpaca: {exec_result.error_message}")

    print("\n======================================================================")
    print("  Ciclo completado. Registros actualizados en logs/trades.jsonl")
    print("======================================================================\n")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Alpaca Autonomous Options Trading Agent")
    parser.add_argument(
        "--mode",
        choices=["scan", "loop", "dry-run"],
        default="scan",
        help="Modo de ejecución: scan (ciclo único), loop (continuo), dry-run (simulación)",
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

    args = parser.parse_args()
    universe = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    print_banner()
    print(f"Modo seleccionado: {args.mode.upper()} | Tickers: {universe}")

    dry_run = args.mode == "dry-run"

    if args.mode in ["scan", "dry-run"]:
        run_trading_cycle(universe=universe, dry_run=dry_run)
    elif args.mode == "loop":
        print(f"Iniciando loop continuo cada {args.interval} segundos. Presiona Ctrl+C para detener.")
        try:
            while True:
                run_trading_cycle(universe=universe, dry_run=dry_run)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nLoop autónomo detenido por el usuario.")


if __name__ == "__main__":
    main()
