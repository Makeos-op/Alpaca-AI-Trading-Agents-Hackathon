"""
Modelos de Datos y Códigos de Razón para el Motor de Riesgo Pre-Trade.
Define las estructuras inmutables para configuración, propuestas de trade,
veredictos de riesgo y códigos tipados de rechazo determinista (Feature F2.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from src.indicators.technicals import to_decimal
from src.options.models import OptionContract


# ==========================================
# Mapeo de Equivalencias entre Códigos
# ==========================================

_REASON_CODE_ALIASES: dict[str, set[str]] = {
    "ERR_WIDE_BID_ASK_SPREAD": {"ERR_SPREAD_EXCEEDS_MAX"},
    "ERR_SPREAD_EXCEEDS_MAX": {"ERR_WIDE_BID_ASK_SPREAD"},
    "ERR_CROSSED_OR_ZERO_QUOTE": {"ERR_SPREAD_INVALID_OR_CROSSED"},
    "ERR_SPREAD_INVALID_OR_CROSSED": {"ERR_CROSSED_OR_ZERO_QUOTE"},
    "ERR_INSUFFICIENT_OPEN_INTEREST": {"ERR_OPEN_INTEREST_BELOW_MIN"},
    "ERR_OPEN_INTEREST_BELOW_MIN": {"ERR_INSUFFICIENT_OPEN_INTEREST"},
    "ERR_INSUFFICIENT_VOLUME": {"ERR_VOLUME_BELOW_MIN"},
    "ERR_VOLUME_BELOW_MIN": {"ERR_INSUFFICIENT_VOLUME"},
    "ERR_DTE_OUT_OF_BOUNDS": {"ERR_DTE_BELOW_MIN", "ERR_DTE_ABOVE_MAX"},
    "ERR_DTE_BELOW_MIN": {"ERR_DTE_OUT_OF_BOUNDS"},
    "ERR_DTE_ABOVE_MAX": {"ERR_DTE_OUT_OF_BOUNDS"},
    "ERR_IV_OUT_OF_BOUNDS": {"ERR_IV_OUT_OF_RANGE"},
    "ERR_IV_OUT_OF_RANGE": {"ERR_IV_OUT_OF_BOUNDS"},
    "ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP": {"ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT"},
    "ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT": {"ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP"},
    "ERR_INSUFFICIENT_BUYING_POWER": {"ERR_INSUFFICIENT_CASH"},
    "ERR_INSUFFICIENT_CASH": {"ERR_INSUFFICIENT_BUYING_POWER"},
    "ERR_ACCOUNT_FROZEN_OR_RESTRICTED": {"ERR_ACCOUNT_FROZEN", "ERR_ACCOUNT_INACTIVE", "ERR_MARGIN_CALL_RISK"},
    "ERR_ACCOUNT_FROZEN": {"ERR_ACCOUNT_FROZEN_OR_RESTRICTED"},
    "ERR_ACCOUNT_INACTIVE": {"ERR_ACCOUNT_FROZEN_OR_RESTRICTED"},
    "ERR_MARGIN_CALL_RISK": {"ERR_ACCOUNT_FROZEN_OR_RESTRICTED"},
}


# ==========================================
# Códigos Tipados de Razón de Riesgo
# ==========================================

class RiskReasonCode(str, Enum):
    """
    Códigos tipados de razón para veredictos del Risk Engine.
    Incorpora los contratos de PROJECT.md / SCOPE.md y las variantes granulares
    especificadas en spec_report.md.
    """
    # Dictamen exitoso
    APPROVED = "APPROVED"

    # Códigos estandarizados (PROJECT.md / SCOPE.md)
    ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT = "ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT"
    ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP = "ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP"
    ERR_INSUFFICIENT_BUYING_POWER = "ERR_INSUFFICIENT_BUYING_POWER"
    ERR_ACCOUNT_FROZEN_OR_RESTRICTED = "ERR_ACCOUNT_FROZEN_OR_RESTRICTED"
    ERR_WIDE_BID_ASK_SPREAD = "ERR_WIDE_BID_ASK_SPREAD"
    ERR_CROSSED_OR_ZERO_QUOTE = "ERR_CROSSED_OR_ZERO_QUOTE"
    ERR_INSUFFICIENT_OPEN_INTEREST = "ERR_INSUFFICIENT_OPEN_INTEREST"
    ERR_INSUFFICIENT_VOLUME = "ERR_INSUFFICIENT_VOLUME"
    ERR_DTE_OUT_OF_BOUNDS = "ERR_DTE_OUT_OF_BOUNDS"
    ERR_DELTA_OUT_OF_BOUNDS = "ERR_DELTA_OUT_OF_BOUNDS"
    ERR_THETA_DECAY_EXCESSIVE = "ERR_THETA_DECAY_EXCESSIVE"
    ERR_IV_OUT_OF_BOUNDS = "ERR_IV_OUT_OF_BOUNDS"

    # Códigos granulares / de reporte (spec_report.md)
    ERR_INSUFFICIENT_CASH = "ERR_INSUFFICIENT_CASH"
    ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT = "ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT"
    ERR_ACCOUNT_FROZEN = "ERR_ACCOUNT_FROZEN"
    ERR_ACCOUNT_INACTIVE = "ERR_ACCOUNT_INACTIVE"
    ERR_MARGIN_CALL_RISK = "ERR_MARGIN_CALL_RISK"
    ERR_ZERO_PORTFOLIO_VALUE = "ERR_ZERO_PORTFOLIO_VALUE"
    ERR_SPREAD_EXCEEDS_MAX = "ERR_SPREAD_EXCEEDS_MAX"
    ERR_SPREAD_INVALID_OR_CROSSED = "ERR_SPREAD_INVALID_OR_CROSSED"
    ERR_OPEN_INTEREST_BELOW_MIN = "ERR_OPEN_INTEREST_BELOW_MIN"
    ERR_VOLUME_BELOW_MIN = "ERR_VOLUME_BELOW_MIN"
    ERR_DTE_BELOW_MIN = "ERR_DTE_BELOW_MIN"
    ERR_DTE_ABOVE_MAX = "ERR_DTE_ABOVE_MAX"
    ERR_IV_OUT_OF_RANGE = "ERR_IV_OUT_OF_RANGE"
    ERR_INVALID_ORDER_QUANTITY = "ERR_INVALID_ORDER_QUANTITY"
    ERR_UNDERLYING_SPREAD_EXCEEDS_MAX = "ERR_UNDERLYING_SPREAD_EXCEEDS_MAX"

    def __eq__(self, other: Any) -> bool:
        if super().__eq__(other):
            return True
        other_str = other.value if hasattr(other, "value") else str(other)
        aliases = _REASON_CODE_ALIASES.get(self.value, set())
        return other_str in aliases

    def __hash__(self) -> int:
        return hash(self.value)


# ==========================================
# Configuración del Motor de Riesgo
# ==========================================

@dataclass(frozen=True)
class RiskConfig:
    """Configuración determinista de umbrales y límites de riesgo."""
    max_risk_pct: Decimal = Decimal("0.05")
    max_portfolio_options_pct: Decimal = Decimal("0.25")
    min_dte: int = 1
    max_dte: int = 30
    max_option_spread_pct: Decimal = Decimal("0.05")  # 5.00%
    max_absolute_spread: Decimal = Decimal("0.50")    # $0.50
    min_open_interest: int = 500
    min_volume: int = 100
    call_delta_min: Decimal = Decimal("0.30")
    call_delta_max: Decimal = Decimal("0.70")
    put_delta_min: Decimal = Decimal("-0.70")
    put_delta_max: Decimal = Decimal("-0.30")
    max_theta_decay_pct: Decimal = Decimal("0.05")    # 5.00% por día
    max_theta_absolute: Decimal = Decimal("0.15")     # $15.00 por contrato por día
    min_iv: Decimal = Decimal("0.05")                 # 5% IV
    max_iv: Decimal = Decimal("1.00")                 # 100% IV
    max_underlying_spread_pct: Decimal = Decimal("0.01")  # 1.00%

    @classmethod
    def create(cls, **kwargs: Any) -> RiskConfig:
        """Crea una instancia convirtiendo números a Decimal."""
        converted = {}
        for k, v in kwargs.items():
            if hasattr(cls, k):
                if isinstance(v, (int, float, str, Decimal)):
                    if k in ("min_dte", "max_dte", "min_open_interest", "min_volume"):
                        converted[k] = int(v)
                    else:
                        converted[k] = to_decimal(v)
                else:
                    converted[k] = v
        return cls(**converted)


# ==========================================
# Propuesta de Trade
# ==========================================

@dataclass(frozen=True)
class TradeProposal:
    """Propuesta estructurada de trade emitida por una estrategia o agente."""
    contract: OptionContract
    quantity: int
    strategy_name: str
    action: str = "BUY"  # BUY / SELL
    max_slippage_pct: Decimal = Decimal("0.02")  # 2% de tolerancia por defecto
    rationale: str = ""
    limit_price: Optional[Decimal] = None
    side: Optional[str] = None

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("La cantidad de contratos debe ser mayor a 0")
        if self.side and not self.action:
            object.__setattr__(self, "action", self.side.upper())
        elif self.action and not self.side:
            object.__setattr__(self, "side", self.action.upper())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.contract.symbol if self.contract else "",
            "quantity": self.quantity,
            "strategy_name": self.strategy_name,
            "action": self.action,
            "side": self.side or self.action,
            "max_slippage_pct": str(self.max_slippage_pct),
            "rationale": self.rationale,
            "limit_price": str(self.limit_price) if self.limit_price is not None else None,
        }


# ==========================================
# Veredicto de Riesgo Pre-Trade
# ==========================================

@dataclass(frozen=True)
class RiskVerdict:
    """
    Resultado formal y determinista de la evaluación del RiskEngine.
    Satisface el contrato de SCOPE.md/PROJECT.md y mantiene retrocompatibilidad total
    con TradeLogger y OptionExecutor.
    """
    is_approved: bool
    reason_code: RiskReasonCode = RiskReasonCode.APPROVED
    message: str = ""
    audited_metrics: dict[str, Any] = field(default_factory=dict)
    max_safe_quantity: int = 0

    # Campos de compatibilidad y detalle financiero
    trade_cost: Decimal = Decimal("0.00")
    max_allowed_budget: Decimal = Decimal("0.00")
    portfolio_risk_pct_used: Decimal = Decimal("0.0000")
    reasons: list[str] = field(default_factory=list)
    reason_codes: list[RiskReasonCode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_quantity: int = 0
    metrics_audited: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Sincronización bidireccional de recommended_quantity y max_safe_quantity
        if self.recommended_quantity != 0 and self.max_safe_quantity == 0:
            object.__setattr__(self, "max_safe_quantity", self.recommended_quantity)
        elif self.max_safe_quantity != 0 and self.recommended_quantity == 0:
            object.__setattr__(self, "recommended_quantity", self.max_safe_quantity)

        # Sincronización de reason_code y reason_codes
        if not self.is_approved:
            if self.reason_codes and self.reason_code == RiskReasonCode.APPROVED:
                object.__setattr__(self, "reason_code", self.reason_codes[0])
            elif self.reason_code != RiskReasonCode.APPROVED and not self.reason_codes:
                object.__setattr__(self, "reason_codes", [self.reason_code])

        # Sincronización de message y reasons
        if self.reasons and not self.message:
            object.__setattr__(self, "message", "; ".join(self.reasons))
        elif self.message and not self.reasons and not self.is_approved:
            object.__setattr__(self, "reasons", [self.message])

        # Sincronización de audited_metrics y metrics_audited
        if self.metrics_audited and not self.audited_metrics:
            object.__setattr__(self, "audited_metrics", dict(self.metrics_audited))
        elif self.audited_metrics and not self.metrics_audited:
            object.__setattr__(self, "metrics_audited", dict(self.audited_metrics))

    def to_dict(self) -> dict[str, Any]:
        """Serializa el veredicto para bitácoras y registros de auditoría."""
        rc_val = self.reason_code.value if hasattr(self.reason_code, "value") else str(self.reason_code)
        rc_list = [rc.value if hasattr(rc, "value") else str(rc) for rc in self.reason_codes]
        return {
            "is_approved": self.is_approved,
            "reason_code": rc_val,
            "message": self.message,
            "trade_cost": str(self.trade_cost),
            "max_allowed_budget": str(self.max_allowed_budget),
            "portfolio_risk_pct_used": str(self.portfolio_risk_pct_used),
            "reasons": list(self.reasons),
            "reason_codes": rc_list,
            "warnings": list(self.warnings),
            "recommended_quantity": self.recommended_quantity,
            "max_safe_quantity": self.max_safe_quantity,
            "audited_metrics": self.audited_metrics,
            "metrics_audited": self.metrics_audited,
        }
