"""
Motor de Riesgo y Validación Pre-Trade (Feature 5: FT-RSK-05).

Actúa como el guardrail determinista central (Diagrama 1) que evalúa si una propuesta de trade
de opciones es segura para la cuenta o debe ser cancelada.
Utiliza estrictamente Decimal para todos los cálculos financieros y porcentajes de riesgo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from src.account import (
    AccountHealth,
    AccountLimits,
    AccountSnapshot,
    calculate_trade_limits,
    check_account_health,
)
from src.config import (
    DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT,
    DEFAULT_MAX_RISK_PER_TRADE_PCT,
    MAX_DTE,
    MAX_OPTION_SPREAD_PCT,
    MIN_DTE,
    MIN_OPTION_OPEN_INTEREST,
)
from src.indicators.technicals import to_decimal
from src.options.models import OptionContract


# ==========================================
# Modelos de Propuesta y Dictamen de Riesgo
# ==========================================

@dataclass(frozen=True)
class TradeProposal:
    """Propuesta estructurada de trade emitida por una estrategia o agente."""
    contract: OptionContract
    quantity: int
    strategy_name: str
    action: str = "BUY"  # BUY / SELL
    max_slippage_pct: Decimal = Decimal("0.02")  # 2% de tolerancia de slippage por defecto

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("La cantidad de contratos debe ser mayor a 0")


@dataclass(frozen=True)
class RiskVerdict:
    """Resultado detallado de la evaluación del Risk Engine."""
    is_approved: bool
    trade_cost: Decimal
    max_allowed_budget: Decimal
    portfolio_risk_pct_used: Decimal  # Costo como % del portfolio value
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_quantity: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serializa el veredicto para bitácoras y registros de auditoría."""
        return {
            "is_approved": self.is_approved,
            "trade_cost": str(self.trade_cost),
            "max_allowed_budget": str(self.max_allowed_budget),
            "portfolio_risk_pct_used": str(self.portfolio_risk_pct_used),
            "reasons": self.reasons,
            "warnings": self.warnings,
            "recommended_quantity": self.recommended_quantity,
        }


# ==========================================
# Motor de Riesgo (RiskEngine)
# ==========================================

class RiskEngine:
    """
    Motor determinista de validación de riesgo pre-trade.
    Aplica la regla del 5% de riesgo máximo, límites de cuenta, liquidez y exposición acumulada.
    """

    def __init__(
        self,
        max_risk_pct: Decimal = DEFAULT_MAX_RISK_PER_TRADE_PCT,
        max_portfolio_options_pct: Decimal = DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT,
    ):
        self.max_risk_pct = to_decimal(max_risk_pct)
        self.max_portfolio_options_pct = to_decimal(max_portfolio_options_pct)

    def calculate_max_safe_contracts(
        self,
        contract: OptionContract,
        max_budget: Decimal,
    ) -> int:
        """
        Calcula la cantidad máxima de contratos que se pueden comprar sin exceder el presupuesto seguro.
        1 contrato = 100 acciones.
        """
        contract_unit_cost = contract.calculate_trade_cost(contracts=1, use_ask=True)
        if contract_unit_cost <= Decimal("0.0"):
            return 0
        max_contracts = int(max_budget // contract_unit_cost)
        return max(0, max_contracts)

    def evaluate_trade(
        self,
        proposal: TradeProposal,
        snapshot: AccountSnapshot,
        current_options_exposure: Decimal = Decimal("0.0"),
    ) -> RiskVerdict:
        """
        Evalúa integralmente la propuesta de trade frente a todas las reglas de riesgo.
        
        Reglas de Validación:
        1. Salud de la cuenta (activa, no congelada, sin margin call).
        2. Regla del 5%: Costo <= 5% del portfolio_value.
        3. Presupuesto efectivo: Costo <= buying_power y cash disponible.
        4. Exposición total acumulada en opciones <= 25% del portfolio_value.
        5. Filtros del contrato de opción: DTE 1-30 días, Open Interest >= 500, Spread <= 5%.
        """
        reasons: list[str] = []
        warnings: list[str] = []

        # 1. Validación de Salud de Cuenta
        health = check_account_health(snapshot)
        if not health.can_trade:
            reasons.extend(health.critical_errors)
        warnings.extend(health.warnings)

        # 2. Cálculo de Límites de Cuenta (Regla 5%)
        limits = calculate_trade_limits(
            snapshot=snapshot,
            max_risk_pct=self.max_risk_pct,
            max_portfolio_risk_pct=self.max_portfolio_options_pct,
        )

        contract = proposal.contract
        trade_cost = contract.calculate_trade_cost(contracts=proposal.quantity, use_ask=True)
        
        # Calcular porcentaje de riesgo sobre el portfolio value
        if limits.portfolio_value > Decimal("0.0"):
            portfolio_risk_pct = (trade_cost / limits.portfolio_value).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            portfolio_risk_pct = Decimal("1.0")

        # 3. Validación de Regla del 5%
        if trade_cost > limits.max_single_trade_risk:
            reasons.append(
                f"El costo del trade (${trade_cost}) excede el límite del {limits.max_risk_pct * Decimal('100.0')}% "
                f"máximo por operación (${limits.max_single_trade_risk})."
            )

        # 4. Validación de Presupuesto Efectivo (Cash y Buying Power)
        if trade_cost > limits.effective_trade_budget:
            reasons.append(
                f"El costo del trade (${trade_cost}) excede el presupuesto efectivo disponible "
                f"(${limits.effective_trade_budget}) en Buying Power o Cash."
            )

        # 5. Validación de Exposición Total Acumulada en Opciones (Máx 25%)
        new_total_options_exposure = current_options_exposure + trade_cost
        if new_total_options_exposure > limits.max_total_options_allocation:
            reasons.append(
                f"La exposición acumulada en opciones (${new_total_options_exposure}) superaría el límite "
                f"máximo permitido del {limits.max_portfolio_risk_pct * Decimal('100.0')}% "
                f"(${limits.max_total_options_allocation})."
            )

        # 6. Validación de Parámetros del Contrato de Opciones
        if contract.dte < MIN_DTE or contract.dte > MAX_DTE:
            reasons.append(
                f"Horizonte DTE inválido ({contract.dte} días). Debe estar entre {MIN_DTE} y {MAX_DTE} días."
            )

        if contract.open_interest < MIN_OPTION_OPEN_INTEREST:
            reasons.append(
                f"Open Interest insuficiente ({contract.open_interest} < {MIN_OPTION_OPEN_INTEREST} contratos)."
            )

        if contract.bid_ask_spread_pct > MAX_OPTION_SPREAD_PCT:
            reasons.append(
                f"Spread Bid/Ask excesivo ({contract.bid_ask_spread_pct * Decimal('100.0')}% > "
                f"{MAX_OPTION_SPREAD_PCT * Decimal('100.0')}%)."
            )

        if contract.bid_price <= Decimal("0.0") or contract.ask_price <= Decimal("0.0"):
            reasons.append("Las cotizaciones Bid o Ask del contrato son cero o inválidas.")

        # 7. Sizing Seguro Recomendado
        recommended_qty = self.calculate_max_safe_contracts(
            contract=contract,
            max_budget=limits.effective_trade_budget,
        )

        is_approved = len(reasons) == 0

        return RiskVerdict(
            is_approved=is_approved,
            trade_cost=trade_cost,
            max_allowed_budget=limits.effective_trade_budget,
            portfolio_risk_pct_used=portfolio_risk_pct,
            reasons=reasons,
            warnings=warnings,
            recommended_quantity=recommended_qty,
        )

