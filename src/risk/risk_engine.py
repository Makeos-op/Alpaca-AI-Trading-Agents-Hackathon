"""
Motor de Riesgo y Validación Pre-Trade (Feature F2.1 - F2.5).

Actúa como el guardrail determinista central que evalúa si una propuesta de trade
de opciones es matemáticamente segura para la cuenta o debe ser estrictamente bloqueada.
Utiliza 100% Decimal para todos los cálculos financieros, porcentajes de riesgo,
spreads y griegas.
"""

from __future__ import annotations

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
from src.options.models import OptionContract, OptionType
from src.risk.models import (
    RiskConfig,
    RiskReasonCode,
    RiskVerdict,
    TradeProposal,
)

__all__ = [
    "RiskConfig",
    "RiskEngine",
    "RiskReasonCode",
    "RiskVerdict",
    "TradeProposal",
]


class RiskEngine:
    """
    Motor determinista de validación de riesgo pre-trade.
    Aplica la regla del 5% de riesgo máximo, límites de cuenta, liquidez,
    umbrales de bid-ask spread, griegas, DTE y exposición acumulada.
    """

    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        max_risk_pct: Optional[Decimal | float | str] = None,
        max_portfolio_options_pct: Optional[Decimal | float | str] = None,
        **kwargs: Any,
    ):
        if config is not None:
            overrides = dict(kwargs)
            if max_risk_pct is not None:
                overrides["max_risk_pct"] = to_decimal(max_risk_pct)
            if max_portfolio_options_pct is not None:
                overrides["max_portfolio_options_pct"] = to_decimal(max_portfolio_options_pct)
            if overrides:
                merged = {**config.__dict__, **overrides}
                self.config = RiskConfig.create(**merged)
            else:
                self.config = config
        else:
            overrides = dict(kwargs)
            if max_risk_pct is not None:
                overrides["max_risk_pct"] = to_decimal(max_risk_pct)
            else:
                overrides.setdefault("max_risk_pct", DEFAULT_MAX_RISK_PER_TRADE_PCT)

            if max_portfolio_options_pct is not None:
                overrides["max_portfolio_options_pct"] = to_decimal(max_portfolio_options_pct)
            else:
                overrides.setdefault("max_portfolio_options_pct", DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT)

            self.config = RiskConfig.create(**overrides)

        self.max_risk_pct = self.config.max_risk_pct
        self.max_portfolio_options_pct = self.config.max_portfolio_options_pct

    def calculate_max_safe_contracts(
        self,
        contract: OptionContract,
        max_budget: Decimal,
        current_options_exposure: Decimal = Decimal("0.0"),
        portfolio_value: Decimal = Decimal("0.0"),
    ) -> int:
        """
        Calcula la cantidad máxima de contratos que se pueden comprar sin exceder
        el presupuesto seguro y el tope acumulado en opciones.
        Q_max_safe = floor(B_effective / (P_ask * 100))
        """
        contract_unit_cost = contract.calculate_trade_cost(contracts=1, use_ask=True)
        if contract_unit_cost <= Decimal("0.0"):
            return 0

        budget = max_budget
        if portfolio_value > Decimal("0.0"):
            total_options_cap = (portfolio_value * self.config.max_portfolio_options_pct).quantize(Decimal("0.01"))
            remaining_cap = max(Decimal("0.0"), total_options_cap - current_options_exposure)
            budget = min(budget, remaining_cap)

        if budget <= Decimal("0.0"):
            return 0

        max_contracts = int(budget // contract_unit_cost)
        return max(0, max_contracts)

    def evaluate_trade(
        self,
        proposal: TradeProposal,
        snapshot: Optional[AccountSnapshot] = None,
        *args: Any,
        contract: Optional[OptionContract] = None,
        underlying_price: Optional[Decimal | Any] = None,
        current_options_exposure: Decimal | Any = Decimal("0.0"),
        account: Optional[AccountSnapshot] = None,
        **kwargs: Any,
    ) -> RiskVerdict:
        """
        Evalúa integralmente la propuesta de trade frente a todas las reglas deterministas de riesgo.

        Reglas de Validación:
        1. Salud de la cuenta (activa, no congelada, sin margin call, equity positivo).
        2. Cotización y Spread: ask > bid > 0, spread pct <= 5%, absolute spread <= $0.50.
        3. Liquidez: volumen de contratos >= 100, open interest >= 500.
        4. Horizonte y DTE: 1 <= DTE <= 30 (bloqueo estricto de 0-DTE pin risk y contratos vencidos).
        5. Griegas:
           - Call Delta in [0.30, 0.70]
           - Put Delta in [-0.70, -0.30]
           - Theta decay diario (|theta| / ask) <= 5.00% y |theta| <= $0.15/día
           - IV in [0.05, 1.00]
        6. Regla del 5%: trade_cost <= 5% portfolio_value.
        7. Presupuesto efectivo: trade_cost <= min(5% cap, buying_power, cash).
        8. Asignación acumulada en opciones: total_options_exposure <= 25% portfolio_value.
        """
        # Resolver snapshot y cuenta
        snap = account if account is not None else snapshot

        # Resolver argumentos posicionales y opcionales
        exposure = to_decimal(current_options_exposure)
        u_price = to_decimal(underlying_price) if underlying_price is not None else None
        opt_contract = contract

        if args:
            if len(args) == 1:
                if isinstance(args[0], OptionContract):
                    opt_contract = args[0]
                else:
                    exposure = to_decimal(args[0])
            elif len(args) == 2:
                opt_contract = args[0]
                u_price = to_decimal(args[1])
            elif len(args) >= 3:
                opt_contract = args[0]
                u_price = to_decimal(args[1])
                exposure = to_decimal(args[2])

        if opt_contract is None and proposal is not None and hasattr(proposal, "contract"):
            opt_contract = proposal.contract

        # Validación estructural de entradas nulas
        if proposal is None or opt_contract is None or snap is None:
            return RiskVerdict(
                is_approved=False,
                reason_code=RiskReasonCode.ERR_INVALID_ORDER_QUANTITY,
                message="Propuesta, contrato o estado de cuenta inválido o nulo.",
                audited_metrics={},
                max_safe_quantity=0,
                trade_cost=Decimal("0.00"),
                max_allowed_budget=Decimal("0.00"),
                portfolio_risk_pct_used=Decimal("0.0000"),
                reasons=["Propuesta, contrato o estado de cuenta inválido o nulo."],
                reason_codes=[RiskReasonCode.ERR_INVALID_ORDER_QUANTITY],
            )

        reasons: list[str] = []
        reason_codes: list[RiskReasonCode] = []
        warnings: list[str] = []

        # 1. Validación de Salud de Cuenta
        health = check_account_health(snap)
        if snap.is_frozen:
            reasons.append("La cuenta está CONGELADA/BLOQUEADA en Alpaca.")
            reason_codes.extend([
                RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED,
                RiskReasonCode.ERR_ACCOUNT_FROZEN,
            ])

        if not snap.is_active:
            reasons.append("La cuenta NO está activa.")
            reason_codes.extend([
                RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED,
                RiskReasonCode.ERR_ACCOUNT_INACTIVE,
            ])

        if snap.portfolio_value <= Decimal("0.0"):
            reasons.append("El valor de la cartera es cero o negativo.")
            reason_codes.extend([
                RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED,
                RiskReasonCode.ERR_ZERO_PORTFOLIO_VALUE,
            ])

        if snap.maintenance_margin > Decimal("0.0") and snap.equity > Decimal("0.0"):
            if snap.maintenance_margin >= snap.equity:
                reasons.append(
                    f"Peligro de Margin Call: Margen de Mantenimiento (${snap.maintenance_margin}) "
                    f"supera o iguala al Equity (${snap.equity})."
                )
                reason_codes.extend([
                    RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED,
                    RiskReasonCode.ERR_MARGIN_CALL_RISK,
                ])

        for crit_err in health.critical_errors:
            if crit_err not in reasons:
                reasons.append(crit_err)
                if not any(rc in reason_codes for rc in (
                    RiskReasonCode.ERR_ACCOUNT_FROZEN,
                    RiskReasonCode.ERR_ACCOUNT_INACTIVE,
                    RiskReasonCode.ERR_MARGIN_CALL_RISK,
                    RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED,
                )):
                    reason_codes.append(RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED)

        warnings.extend(health.warnings)

        # 2. Validación de Cotizaciones y Spread de Opciones
        is_quote_invalid = (
            opt_contract.bid_price <= Decimal("0.0")
            or opt_contract.ask_price <= Decimal("0.0")
            or opt_contract.ask_price <= opt_contract.bid_price
        )
        if is_quote_invalid:
            reasons.append(
                f"Cotizaciones Bid (${opt_contract.bid_price}) o Ask (${opt_contract.ask_price}) "
                f"inválidas o cruzadas (Ask <= Bid o cotizaciones <= 0)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE,
                RiskReasonCode.ERR_SPREAD_INVALID_OR_CROSSED,
            ])

        # Spread porcentual en opciones (<= 5.00%)
        if opt_contract.bid_ask_spread_pct > self.config.max_option_spread_pct:
            reasons.append(
                f"Spread Bid/Ask excesivo ({opt_contract.bid_ask_spread_pct * Decimal('100.0')}% > "
                f"{self.config.max_option_spread_pct * Decimal('100.0')}%)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD,
                RiskReasonCode.ERR_SPREAD_EXCEEDS_MAX,
            ])

        # Spread absoluto en opciones (<= $0.50)
        abs_spread = opt_contract.ask_price - opt_contract.bid_price
        if abs_spread > self.config.max_absolute_spread:
            reasons.append(
                f"Spread Bid/Ask absoluto excesivo (${abs_spread} > ${self.config.max_absolute_spread})."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD,
                RiskReasonCode.ERR_SPREAD_EXCEEDS_MAX,
            ])

        # Spread del activo subyacente (<= 1.00%)
        if "underlying_spread_pct" in kwargs:
            u_spread = to_decimal(kwargs["underlying_spread_pct"])
            if u_spread > self.config.max_underlying_spread_pct:
                reasons.append(
                    f"Spread del subyacente excesivo ({u_spread * Decimal('100.0')}% > "
                    f"{self.config.max_underlying_spread_pct * Decimal('100.0')}%)."
                )
                reason_codes.extend([
                    RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD,
                    RiskReasonCode.ERR_UNDERLYING_SPREAD_EXCEEDS_MAX,
                ])
        elif "underlying_bid" in kwargs and "underlying_ask" in kwargs:
            u_bid = to_decimal(kwargs["underlying_bid"])
            u_ask = to_decimal(kwargs["underlying_ask"])
            u_mid = (u_bid + u_ask) / Decimal("2.0")
            if u_mid > Decimal("0.0"):
                u_spread = (u_ask - u_bid) / u_mid
                if u_spread > self.config.max_underlying_spread_pct:
                    reasons.append(
                        f"Spread del subyacente excesivo ({u_spread * Decimal('100.0')}% > "
                        f"{self.config.max_underlying_spread_pct * Decimal('100.0')}%)."
                    )
                    reason_codes.extend([
                        RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD,
                        RiskReasonCode.ERR_UNDERLYING_SPREAD_EXCEEDS_MAX,
                    ])

        # 3. Validación de Liquidez del Contrato
        if opt_contract.open_interest < self.config.min_open_interest:
            reasons.append(
                f"Open Interest insuficiente ({opt_contract.open_interest} < {self.config.min_open_interest} contratos)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_INSUFFICIENT_OPEN_INTEREST,
                RiskReasonCode.ERR_OPEN_INTEREST_BELOW_MIN,
            ])

        if opt_contract.volume < self.config.min_volume:
            reasons.append(
                f"Volumen diario de contratos insuficiente ({opt_contract.volume} < {self.config.min_volume} contratos)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_INSUFFICIENT_VOLUME,
                RiskReasonCode.ERR_VOLUME_BELOW_MIN,
            ])

        # 4. Validación de Horizonte y DTE (1 a 30 días)
        if opt_contract.dte < self.config.min_dte:
            reasons.append(
                f"Horizonte DTE inválido ({opt_contract.dte} días < {self.config.min_dte} días). "
                f"Bloqueo estricto de pin risk y expiración inmediata (0-DTE)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS,
                RiskReasonCode.ERR_DTE_BELOW_MIN,
            ])
        elif opt_contract.dte > self.config.max_dte:
            reasons.append(
                f"Horizonte DTE inválido ({opt_contract.dte} días > {self.config.max_dte} días). "
                f"Supera el horizonte máximo de swing trading ({self.config.max_dte} días)."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS,
                RiskReasonCode.ERR_DTE_ABOVE_MAX,
            ])

        # 5. Validación de Griegas y Volatilidad
        c_type_str = opt_contract.contract_type.value if hasattr(opt_contract.contract_type, "value") else str(opt_contract.contract_type)
        c_type_upper = c_type_str.upper()
        delta = opt_contract.greeks.delta

        if "CALL" in c_type_upper:
            if delta < self.config.call_delta_min or delta > self.config.call_delta_max:
                reasons.append(
                    f"Delta de CALL fuera de rango permitido ({delta} no está en "
                    f"[{self.config.call_delta_min}, {self.config.call_delta_max}])."
                )
                reason_codes.append(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)
        elif "PUT" in c_type_upper:
            if delta < self.config.put_delta_min or delta > self.config.put_delta_max:
                reasons.append(
                    f"Delta de PUT fuera de rango permitido ({delta} no está en "
                    f"[{self.config.put_delta_min}, {self.config.put_delta_max}])."
                )
                reason_codes.append(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)
        else:
            if abs(delta) < self.config.call_delta_min or abs(delta) > self.config.call_delta_max:
                reasons.append(f"Delta fuera de rango permitido ({delta}).")
                reason_codes.append(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)

        # Validación de Decaimiento Theta
        theta = opt_contract.greeks.theta
        if opt_contract.ask_price > Decimal("0.0"):
            theta_decay_rate = (abs(theta) / opt_contract.ask_price).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            if theta_decay_rate > self.config.max_theta_decay_pct or abs(theta) > self.config.max_theta_absolute:
                reasons.append(
                    f"Tasa de decaimiento Theta diaria excesiva ({theta_decay_rate * Decimal('100.0')}% > "
                    f"{self.config.max_theta_decay_pct * Decimal('100.0')}% diario o |theta| > ${self.config.max_theta_absolute})."
                )
                reason_codes.append(RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE)

        # Validación de Volatilidad Implícita (IV)
        iv = opt_contract.greeks.implied_volatility
        if iv < self.config.min_iv or iv > self.config.max_iv:
            reasons.append(
                f"Volatilidad Implícita (IV) fuera de rango ({iv} no está en "
                f"[{self.config.min_iv}, {self.config.max_iv}])."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_IV_OUT_OF_BOUNDS,
                RiskReasonCode.ERR_IV_OUT_OF_RANGE,
            ])

        # 6. Cálculo de Límites de Cuenta y Regla del 5%
        limits = calculate_trade_limits(
            snapshot=snap,
            max_risk_pct=self.config.max_risk_pct,
            max_portfolio_risk_pct=self.config.max_portfolio_options_pct,
        )

        effective_price = opt_contract.ask_price
        if proposal.limit_price is not None and proposal.limit_price > effective_price:
            effective_price = proposal.limit_price

        trade_cost = (
            effective_price * Decimal("100") * Decimal(str(proposal.quantity))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if limits.portfolio_value > Decimal("0.0"):
            portfolio_risk_pct = (trade_cost / limits.portfolio_value).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            portfolio_risk_pct = Decimal("1.0000")

        # Regla del 5%
        if trade_cost > limits.max_single_trade_risk:
            reasons.append(
                f"El costo del trade (${trade_cost}) excede el límite del "
                f"{limits.max_risk_pct * Decimal('100.0')}% máximo por operación (${limits.max_single_trade_risk})."
            )
            reason_codes.append(RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)

        # Presupuesto efectivo (Buying Power y Cash)
        if trade_cost > limits.effective_trade_budget:
            reasons.append(
                f"El costo del trade (${trade_cost}) excede el presupuesto efectivo disponible "
                f"(${limits.effective_trade_budget}) en Buying Power o Cash."
            )
            if trade_cost > snap.cash:
                reason_codes.extend([
                    RiskReasonCode.ERR_INSUFFICIENT_CASH,
                    RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER,
                ])
            else:
                reason_codes.append(RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER)

        # Límite de exposición acumulada en opciones (25%)
        new_total_options_exposure = exposure + trade_cost
        if new_total_options_exposure > limits.max_total_options_allocation:
            reasons.append(
                f"La exposición acumulada en opciones (${new_total_options_exposure}) superaría el límite "
                f"máximo permitido del {limits.max_portfolio_risk_pct * Decimal('100.0')}% "
                f"(${limits.max_total_options_allocation})."
            )
            reason_codes.extend([
                RiskReasonCode.ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT,
                RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP,
            ])

        # 7. Sizing Seguro Recomendado (Cantidad máxima de contratos permitida)
        recommended_qty = self.calculate_max_safe_contracts(
            contract=opt_contract,
            max_budget=limits.effective_trade_budget,
            current_options_exposure=exposure,
            portfolio_value=limits.portfolio_value,
        )

        is_approved = len(reasons) == 0

        # Compilación de códigos sin duplicados
        seen_codes: set[str] = set()
        deduped_reason_codes: list[RiskReasonCode] = []
        for rc in reason_codes:
            rc_val = rc.value if hasattr(rc, "value") else str(rc)
            if rc_val not in seen_codes:
                seen_codes.add(rc_val)
                deduped_reason_codes.append(rc)

        if is_approved:
            primary_reason_code = RiskReasonCode.APPROVED
            summary_message = "Trade aprobado: cumple todos los criterios deterministas de riesgo."
        else:
            primary_reason_code = deduped_reason_codes[0] if deduped_reason_codes else RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT
            summary_message = "; ".join(reasons)

        audited_metrics: dict[str, Any] = {
            "portfolio_value": str(snap.portfolio_value),
            "buying_power": str(snap.buying_power),
            "cash": str(snap.cash),
            "trade_cost": str(trade_cost),
            "max_allowed_risk": str(limits.max_single_trade_risk),
            "max_allowed_budget": str(limits.effective_trade_budget),
            "effective_budget": str(limits.effective_trade_budget),
            "portfolio_risk_pct": str((portfolio_risk_pct * Decimal("100.0")).quantize(Decimal("0.01"))),
            "portfolio_risk_pct_used": str(portfolio_risk_pct),
            "current_options_exposure": str(exposure),
            "projected_options_exposure": str(new_total_options_exposure),
            "max_total_options_allocation": str(limits.max_total_options_allocation),
            "spread_pct": str((opt_contract.bid_ask_spread_pct * Decimal("100.0")).quantize(Decimal("0.01"))),
            "dte": opt_contract.dte,
            "volume": opt_contract.volume,
            "open_interest": opt_contract.open_interest,
            "delta": str(opt_contract.greeks.delta),
            "theta": str(opt_contract.greeks.theta),
            "implied_volatility": str(opt_contract.greeks.implied_volatility),
            "recommended_quantity": recommended_qty,
            "max_safe_quantity": recommended_qty,
        }

        return RiskVerdict(
            is_approved=is_approved,
            reason_code=primary_reason_code,
            message=summary_message,
            audited_metrics=audited_metrics,
            max_safe_quantity=recommended_qty,
            trade_cost=trade_cost,
            max_allowed_budget=limits.effective_trade_budget,
            portfolio_risk_pct_used=portfolio_risk_pct,
            reasons=reasons,
            reason_codes=deduped_reason_codes,
            warnings=warnings,
            recommended_quantity=recommended_qty,
            metrics_audited=audited_metrics,
        )
