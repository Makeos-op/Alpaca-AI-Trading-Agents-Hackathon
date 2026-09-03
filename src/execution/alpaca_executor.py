"""
Módulo de Ejecución de Órdenes de Opciones y Herramientas MCP (Feature 2: FT-MCP-02 & Feature 6: FT-AGT-06).

Conecta la aprobación determinista del Risk Engine con la API de Alpaca Paper Trading
y expone funciones de interfaz de herramientas para agentes IA (MCP Tools).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from src.account import (
    AccountSnapshot,
    get_account_snapshot,
    get_trading_client,
)
from src.data.market import MarketDataService, screen_ticker_liquidity
from src.execution.trade_logger import TradeLogger
from src.indicators.technicals import to_decimal
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado formal de la ejecución de una orden en Alpaca."""
    success: bool
    order_id: Optional[str]
    symbol: str
    quantity: int
    status: str  # "FILLED" | "NEW" | "REJECTED" | "ERROR"
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
    """

    def __init__(
        self,
        trading_client: Optional[TradingClient] = None,
        logger: Optional[TradeLogger] = None,
    ):
        self.client = trading_client
        self.logger = logger or TradeLogger()

    def _get_client(self) -> TradingClient:
        if self.client is None:
            self.client = get_trading_client()
        return self.client

    def execute_approved_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
        use_limit_order: bool = False,
        limit_price: Optional[Decimal] = None,
    ) -> ExecutionResult:
        """
        Ejecuta la orden en Alpaca Paper Trading SOLO si el veredicto de riesgo es aprobado.
        Si es rechazado, bloquea la orden y genera el log de auditoría correspondiente.
        """
        contract = proposal.contract

        # 1. Guardrail Infranqueable: Rechazo de Risk Engine
        if not verdict.is_approved:
            self.logger.log_rejected_trade(proposal, verdict)
            reasons_str = "; ".join(verdict.reasons)
            return ExecutionResult(
                success=False,
                order_id=None,
                symbol=contract.symbol,
                quantity=proposal.quantity,
                status="REJECTED",
                error_message=f"Orden cancelada por el Risk Engine: {reasons_str}",
            )

        # 2. Preparación de la Orden
        side = OrderSide.BUY if proposal.action.upper() == "BUY" else OrderSide.SELL

        try:
            client = self._get_client()

            if use_limit_order:
                l_price = float(limit_price or contract.ask_price)
                req = LimitOrderRequest(
                    symbol=contract.symbol,
                    qty=proposal.quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=l_price,
                )
            else:
                req = MarketOrderRequest(
                    symbol=contract.symbol,
                    qty=proposal.quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                )

            # Envío a Alpaca Paper Trading
            order = client.submit_order(req)
            order_id = str(getattr(order, "id", getattr(order, "client_order_id", "sim-order")))
            status = str(getattr(order, "status", "FILLED")).upper()
            fill_price_raw = getattr(order, "filled_avg_price", getattr(order, "limit_price", None))
            fill_price = to_decimal(fill_price_raw) if fill_price_raw else contract.ask_price

            # Registrar trade ejecutado
            self.logger.log_executed_trade(
                proposal=proposal,
                verdict=verdict,
                order_id=order_id,
                fill_price=fill_price,
                status=status,
            )

            return ExecutionResult(
                success=True,
                order_id=order_id,
                symbol=contract.symbol,
                quantity=proposal.quantity,
                status=status,
                filled_avg_price=fill_price,
            )

        except Exception as exc:
            error_msg = f"Error al emitir orden de opciones en Alpaca: {exc}"
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
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                symbol=contract.symbol,
                quantity=proposal.quantity,
                status="ERROR",
                error_message=error_msg,
            )


# ==========================================
# Funciones de Interfaz MCP (MCP Tool Wrappers)
# ==========================================

def mcp_get_account_snapshot() -> dict[str, Any]:
    """Herramienta MCP: Retorna el snapshot completo de la cuenta."""
    snapshot = get_account_snapshot()
    return snapshot.to_dict()


def mcp_get_screened_universe(stats_by_ticker: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Herramienta MCP: Pipeline unificado que evalúa una propuesta en el Risk Engine y la ejecuta."""
    contract = OptionContract.create(
        symbol=contract_data["symbol"],
        underlying_symbol=contract_data["underlying_symbol"],
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

    account_snap = snapshot or get_account_snapshot()
    re = risk_engine or RiskEngine()
    verdict = re.evaluate_trade(proposal, account_snap)
    ex = executor or OptionExecutor()
    result = ex.execute_approved_trade(proposal, verdict)

    return {
        "verdict": verdict.to_dict(),
        "execution": result.to_dict(),
    }
