"""
Módulo de Ejecución de Órdenes de Opciones y Herramientas MCP (Feature F1.3, F1.4 & F3.1).

Conecta la aprobación determinista del Risk Engine con AlpacaGateway (MCP Stdio / CLI / Mock)
y expone funciones de interfaz de herramientas para agentes IA (MCP Tools).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from src.account import (
    AccountSnapshot,
    get_account_snapshot,
)
from src.data.market import MarketDataService, screen_ticker_liquidity
from src.execution.mcp_gateway import AlpacaGateway
from src.execution.trade_logger import TradeLogger
from src.indicators.technicals import to_decimal
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado formal de la ejecución de una orden en Alpaca o simulación."""
    success: bool
    order_id: Optional[str]
    symbol: str
    quantity: int
    status: str  # "FILLED" | "NEW" | "REJECTED" | "SIMULATED" | "ERROR"
    filled_avg_price: Optional[Decimal] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "status": self.status,
            "filled_avg_price": str(self.filled_avg_price) if self.filled_avg_price is not None else None,
            "error_message": self.error_message,
        }


class OptionExecutor:
    """
    Ejecutor de órdenes de opciones que verifica el dictamen del Risk Engine antes de operar.
    Utiliza AlpacaGateway para comunicarse con Alpaca Paper Trading vía MCP stdio / CLI.
    """

    def __init__(
        self,
        gateway: Optional[AlpacaGateway] = None,
        trading_client: Optional[Any] = None,
        logger: Optional[TradeLogger] = None,
        dry_run: bool = False,
        mode: str = "scan",
    ):
        self.logger = logger or TradeLogger()
        self.dry_run = dry_run
        self.mode = "dry-run" if dry_run else mode

        if gateway is not None:
            self.gateway = gateway
            self.trading_client = None
        elif trading_client is not None:
            if isinstance(trading_client, AlpacaGateway):
                self.gateway = trading_client
                self.trading_client = None
            else:
                self.gateway = None
                self.trading_client = trading_client
        else:
            self.gateway = None
            self.trading_client = None

    def _get_gateway(self) -> AlpacaGateway:
        """Obtiene o inicializa la instancia de AlpacaGateway."""
        if self.gateway is None:
            if self.trading_client is not None and hasattr(self.trading_client, "submit_option_order"):
                return self.trading_client
            self.gateway = AlpacaGateway(mode="auto")
        return self.gateway

    def execute_approved_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
        use_limit_order: bool = False,
        limit_price: Optional[Decimal] = None,
        dry_run: Optional[bool] = None,
    ) -> ExecutionResult:
        """
        Ejecuta la orden en Alpaca Paper Trading SOLO si el veredicto de riesgo es aprobado.
        Si es rechazado, bloquea la orden inmediatamente y registra en auditoría.
        En modo dry-run, simula la ejecución con cero mutaciones en broker.
        """
        contract = proposal.contract
        is_dry = self.dry_run if dry_run is None else dry_run
        current_mode = "dry-run" if is_dry else self.mode
        is_equity = (
            getattr(proposal, "is_equity", False)
            or (getattr(proposal, "asset_class", "option") or "option").lower() in ("equity", "stock")
            or contract is None
        )
        target_symbol = (
            getattr(proposal, "target_symbol", "")
            or getattr(proposal, "symbol", "")
            or (contract.symbol if contract else "")
        )

        # 1. Guardrail Infranqueable: Rechazo de Risk Engine (CERO llamadas a broker)
        if not verdict.is_approved:
            self.logger.log_rejected_trade(proposal, verdict, mode=current_mode)
            reasons_str = "; ".join(verdict.reasons) if verdict.reasons else (verdict.message or str(verdict.reason_code))
            return ExecutionResult(
                success=False,
                order_id=None,
                symbol=target_symbol,
                quantity=proposal.quantity,
                status="REJECTED",
                error_message=f"Orden cancelada por el Risk Engine: {reasons_str}",
            )

        # 2. Modo Dry-Run: Simulación de ejecución con cero mutaciones en broker
        if is_dry:
            sim_order_id = f"dry-run-order-{uuid.uuid4().hex[:8]}"
            ref_price = (
                limit_price
                or (contract.ask_price if contract else None)
                or getattr(proposal, "ask_price", None)
                or getattr(proposal, "price", Decimal("100.00"))
            )
            self.logger.log_executed_trade(
                proposal=proposal,
                verdict=verdict,
                order_id=sim_order_id,
                fill_price=ref_price,
                status="SIMULATED",
                mode="dry-run",
            )
            return ExecutionResult(
                success=True,
                order_id=sim_order_id,
                symbol=target_symbol,
                quantity=proposal.quantity,
                status="SIMULATED",
                filled_avg_price=ref_price,
            )

        # 3. Ejecución Real / Paper Trading vía Gateway
        side = proposal.action.lower() if proposal.action else (proposal.side.lower() if proposal.side else "buy")
        order_type = "limit" if use_limit_order else "market"

        try:
            # Compatibilidad con clientes/mocks legacy en pruebas unitarias.
            # __init__ garantiza mutua exclusividad entre self.gateway y self.trading_client,
            # por lo que basta con que trading_client esté presente para usar la ruta legacy.
            if self.trading_client is not None:
                order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
                ref_ask = (
                    contract.ask_price
                    if contract
                    else (getattr(proposal, "ask_price", None) or getattr(proposal, "price", Decimal("100.00")))
                )
                if use_limit_order:
                    req = LimitOrderRequest(
                        symbol=target_symbol,
                        qty=proposal.quantity,
                        side=order_side,
                        time_in_force=TimeInForce.DAY,
                        limit_price=float(limit_price or ref_ask),
                    )
                else:
                    req = MarketOrderRequest(
                        symbol=target_symbol,
                        qty=proposal.quantity,
                        side=order_side,
                        time_in_force=TimeInForce.DAY,
                    )
                order = self.trading_client.submit_order(req)
                order_id = str(getattr(order, "id", getattr(order, "client_order_id", "order-legacy")))
                status = str(getattr(order, "status", "FILLED")).upper()
                fill_raw = getattr(order, "filled_avg_price", getattr(order, "limit_price", None))
                fill_price = to_decimal(fill_raw) if fill_raw else ref_ask
            else:
                gw = self._get_gateway()
                ref_ask = (
                    contract.ask_price
                    if contract
                    else (getattr(proposal, "ask_price", None) or getattr(proposal, "price", Decimal("100.00")))
                )

                if is_equity:
                    if hasattr(gw, "submit_stock_order"):
                        order_dict = gw.submit_stock_order(
                            symbol=target_symbol,
                            qty=proposal.quantity,
                            side=side,
                            time_in_force="day",
                            order_type=order_type,
                            limit_price=limit_price,
                        )
                    else:
                        order_dict = gw.submit_order(
                            symbol=target_symbol,
                            qty=proposal.quantity,
                            side=side,
                            time_in_force="day",
                            order_type=order_type,
                            limit_price=limit_price,
                        )
                else:
                    if hasattr(gw, "submit_option_order"):
                        order_dict = gw.submit_option_order(
                            symbol=target_symbol,
                            qty=proposal.quantity,
                            side=side,
                            time_in_force="day",
                            order_type=order_type,
                            limit_price=limit_price,
                        )
                    else:
                        order_dict = gw.submit_order(
                            symbol=target_symbol,
                            qty=proposal.quantity,
                            side=side,
                            time_in_force="day",
                            order_type=order_type,
                            limit_price=limit_price,
                        )

                order_id = str(order_dict.get("id") or order_dict.get("client_order_id") or f"order-{uuid.uuid4().hex[:8]}")
                status = str(order_dict.get("status", "FILLED")).upper()
                raw_fill = order_dict.get("filled_avg_price") or limit_price or ref_ask
                fill_price = to_decimal(raw_fill)

            self.logger.log_executed_trade(
                proposal=proposal,
                verdict=verdict,
                order_id=order_id,
                fill_price=fill_price,
                status=status,
                mode=current_mode,
            )
            return ExecutionResult(
                success=True,
                order_id=order_id,
                symbol=target_symbol,
                quantity=proposal.quantity,
                status=status,
                filled_avg_price=fill_price,
            )

        except Exception as exc:
            asset_label = "acciones" if is_equity else "opciones"
            error_msg = f"Error al emitir orden de {asset_label} en Alpaca: {exc}"
            self.logger.log_rejected_trade(
                proposal=proposal,
                verdict=RiskVerdict(
                    is_approved=False,
                    trade_cost=verdict.trade_cost,
                    max_allowed_budget=verdict.max_allowed_budget,
                    portfolio_risk_pct_used=verdict.portfolio_risk_pct_used,
                    reasons=[error_msg],
                    warnings=verdict.warnings,
                ),
                mode=current_mode,
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                symbol=target_symbol,
                quantity=proposal.quantity,
                status="ERROR",
                error_message=error_msg,
            )

    def execute_equity_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
        use_limit_order: bool = False,
        limit_price: Optional[Decimal] = None,
        dry_run: Optional[bool] = None,
    ) -> ExecutionResult:
        """Método específico para ejecutar órdenes de acciones o ETFs aprobadas."""
        return self.execute_approved_trade(
            proposal=proposal,
            verdict=verdict,
            use_limit_order=use_limit_order,
            limit_price=limit_price,
            dry_run=dry_run,
        )

    def fallback_to_equity(
        self,
        proposal: TradeProposal,
        account: Optional[AccountSnapshot] = None,
        risk_engine: Optional[RiskEngine] = None,
        underlying_price: Optional[Decimal | float | str] = None,
        fallback_symbol: Optional[str] = None,
        quantity: Optional[int] = None,
        use_limit_order: bool = False,
        limit_price: Optional[Decimal] = None,
        dry_run: Optional[bool] = None,
    ) -> ExecutionResult:
        """
        Fallback determinista a acciones/ETFs (ej. SPY, AAPL) cuando los contratos de
        opciones no están disponibles, son ilíquidos o el mercado de opciones está cerrado.
        Evalúa la orden a través del RiskEngine y la ejecuta únicamente si es aprobada.
        """
        sym = (
            fallback_symbol
            or getattr(proposal, "underlying_symbol", None)
            or getattr(proposal, "symbol", None)
            or (proposal.contract.underlying_symbol if proposal.contract else "SPY")
        )
        re = risk_engine or RiskEngine()
        snap = account or self._get_gateway().get_account()

        u_price = to_decimal(underlying_price) if underlying_price is not None else Decimal("500.00")
        qty = quantity if quantity is not None and quantity > 0 else max(1, proposal.quantity)

        equity_proposal = TradeProposal(
            symbol=sym,
            quantity=qty,
            strategy_name=f"{proposal.strategy_name}_EquityFallback",
            action=proposal.action or "BUY",
            asset_class="equity",
            price=u_price,
            ask_price=u_price,
            bid_price=u_price,
            rationale=f"Fallback a acciones por indisponibilidad de opciones: {sym}",
        )

        verdict = re.evaluate_proposal(equity_proposal, snap)
        return self.execute_approved_trade(
            proposal=equity_proposal,
            verdict=verdict,
            use_limit_order=use_limit_order,
            limit_price=limit_price,
            dry_run=dry_run,
        )


# Alias unificados para la capa de ejecución multi-activo
AlpacaOrderExecutor = OptionExecutor
AlpacaExecutor = OptionExecutor


# ==========================================
# Funciones de Interfaz MCP (MCP Tool Wrappers)
# ==========================================

def mcp_get_account_snapshot(gateway: Optional[AlpacaGateway] = None) -> dict[str, Any]:
    """Herramienta MCP: Retorna el snapshot completo de la cuenta consultado vía AlpacaGateway."""
    gw = gateway or AlpacaGateway(mode="auto")
    snapshot = gw.get_account()
    return snapshot.to_dict()


def mcp_get_screened_universe(
    stats_by_ticker: Optional[dict[str, dict[str, Any]]] = None,
    gateway: Optional[AlpacaGateway] = None,
) -> dict[str, Any]:
    """Herramienta MCP: Evalúa la liquidez de los tickers del universo de inversión."""
    service = MarketDataService()
    scores = service.screen_universe(stats_by_ticker or {})
    return {k: v.to_dict() for k, v in scores.items()}


def mcp_evaluate_and_execute_option_trade(
    contract_data: dict[str, Any],
    quantity: int,
    strategy_name: str,
    action: str = "BUY",
    snapshot: Optional[AccountSnapshot] = None,
    risk_engine: Optional[RiskEngine] = None,
    executor: Optional[OptionExecutor] = None,
    gateway: Optional[AlpacaGateway] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Herramienta MCP: Pipeline unificado que evalúa una propuesta en el Risk Engine y la ejecuta vía Gateway."""
    underlying_sym = contract_data.get("underlying_symbol") or contract_data.get("symbol", "")[:4]
    contract = OptionContract.create(
        symbol=contract_data["symbol"],
        underlying_symbol=underlying_sym,
        contract_type=contract_data["contract_type"],
        strike_price=contract_data["strike_price"],
        expiration_date=contract_data["expiration_date"],
        dte=int(contract_data["dte"]),
        bid_price=contract_data["bid_price"],
        ask_price=contract_data["ask_price"],
        open_interest=int(contract_data.get("open_interest", 0)),
        volume=int(contract_data.get("volume", 0)),
        delta=contract_data.get("delta", "0.0"),
        gamma=contract_data.get("gamma", "0.0"),
        theta=contract_data.get("theta", "0.0"),
        vega=contract_data.get("vega", "0.0"),
        implied_volatility=contract_data.get("implied_volatility", "0.0"),
    )

    proposal = TradeProposal(
        contract=contract,
        quantity=quantity,
        strategy_name=strategy_name,
        action=action,
    )

    gw = gateway or (executor.gateway if executor and executor.gateway else AlpacaGateway(mode="auto"))
    account_snap = snapshot or gw.get_account()
    re = risk_engine or RiskEngine()
    verdict = re.evaluate_trade(proposal, account_snap)
    ex = executor or OptionExecutor(gateway=gw, dry_run=dry_run)
    result = ex.execute_approved_trade(proposal, verdict, dry_run=dry_run)

    return {
        "verdict": verdict.to_dict(),
        "execution": result.to_dict(),
    }
