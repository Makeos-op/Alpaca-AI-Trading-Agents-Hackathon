"""
Orquestador Principal del Sistema de Trading Autónomo de Opciones en Alpaca (Paper Trading).

Uso:
    python src/main.py --mode scan       # Ejecuta un ciclo de escaneo y trading en Paper Trading
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
)
from src.agents.strategy_agent import AutonomousStrategyAgent, SignalType, TradingSignal
from src.config import DEFAULT_UNIVERSE
from src.data.market import LiquidityScore, MarketDataService, screen_ticker_liquidity
from src.execution.alpaca_executor import ExecutionResult, OptionExecutor
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
  ALPACA AI OPTIONS AUTONOMOUS TRADING AGENT
  Paper Trading Environment | 100% Decimal Precision | 5% Risk Engine
======================================================================
"""
    print(banner)


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
            print(f"  * [DRY-RUN] Modo simulación activado.")
        else:
            print(f"  * Enviando orden a Alpaca Paper Trading...")

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
