"""
Módulo de Gestión de Cuenta y Límites Financieros (Feature 1: FT-ACC-01).

Proporciona:
- Extracción tipada del estado de la cuenta en Alpaca Paper Trading (`AccountSnapshot`).
- Cálculo determinista del set de límites de riesgo (Regla del 5% max risk) (`AccountLimits`).
- Guardrail de salud y verificación de estado de cuenta (`AccountHealth`).
- Validador pre-trade de coste vs presupuesto.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from alpaca.trading.client import TradingClient
from dotenv import load_dotenv


# ==========================================
# Excepciones Personalizadas
# ==========================================

class AccountError(Exception):
    """Excepción base para errores relacionados con la cuenta."""
    pass


class AccountAuthError(AccountError):
    """Error cuando faltan credenciales o son inválidas."""
    pass


class AccountConnectionError(AccountError):
    """Error al comunicarse con la API de Alpaca."""
    pass


# ==========================================
# Modelos de Datos Tipados
# ==========================================

@dataclass(frozen=True)
class AccountSnapshot:
    """Snapshot inmutable y tipado del estado de la cuenta en Alpaca."""
    account_id: str
    cash: Decimal
    portfolio_value: Decimal
    buying_power: Decimal
    equity: Decimal
    long_market_value: Decimal
    short_market_value: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal
    daytrading_buying_power: Decimal
    daytrading_count: int
    is_daytrader: bool
    is_active: bool
    is_frozen: bool
    raw_data: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_alpaca_account(cls, tc_info: Any) -> AccountSnapshot:
        """Construye un AccountSnapshot a partir de un objeto o diccionario de cuenta de Alpaca."""
        def _to_decimal(val: Any, default: str = "0.0") -> Decimal:
            if val is None:
                return Decimal(default)
            try:
                return Decimal(str(val))
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(default)

        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        raw = {}
        if isinstance(tc_info, dict):
            raw = {str(k): str(v) for k, v in tc_info.items()}
        elif hasattr(tc_info, "__dict__"):
            raw = {k: str(v) for k, v in tc_info.__dict__.items() if not k.startswith("_")}

        status_raw = _get(tc_info, "status", "ACTIVE")
        status_val = str(getattr(status_raw, "value", status_raw)).upper()
        
        is_active_attr = _get(tc_info, "is_active", None)
        is_active = (
            bool(is_active_attr)
            if is_active_attr is not None
            else (status_val in ["ACTIVE", "APPROVED", "ONBOARDING", "ACCOUNTSTATUS.ACTIVE"] or "ACTIVE" in status_val)
        )
        is_frozen = bool(
            _get(tc_info, "is_frozen", False) is True
            or _get(tc_info, "account_blocked", False) is True
            or _get(tc_info, "trading_blocked", False) is True
        )

        acc_id = str(_get(tc_info, "account_id", _get(tc_info, "id", "")) or "")

        return cls(
            account_id=acc_id,
            cash=_to_decimal(_get(tc_info, "cash", 0)),
            portfolio_value=_to_decimal(_get(tc_info, "portfolio_value", 0)),
            buying_power=_to_decimal(_get(tc_info, "buying_power", 0)),
            equity=_to_decimal(_get(tc_info, "equity", 0)),
            long_market_value=_to_decimal(_get(tc_info, "long_market_value", 0)),
            short_market_value=_to_decimal(_get(tc_info, "short_market_value", 0)),
            initial_margin=_to_decimal(_get(tc_info, "initial_margin", 0)),
            maintenance_margin=_to_decimal(_get(tc_info, "maintenance_margin", 0)),
            daytrading_buying_power=_to_decimal(_get(tc_info, "daytrading_buying_power", 0)),
            daytrading_count=int(_get(tc_info, "daytrading_count", _get(tc_info, "daytrade_count", 0)) or 0),
            is_daytrader=bool(_get(tc_info, "is_daytrader", False)),
            is_active=bool(is_active),
            is_frozen=bool(is_frozen),
            raw_data=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        """Exporta el snapshot a un diccionario amigable para serialización JSON."""
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = str(value)
        return data


@dataclass(frozen=True)
class AccountLimits:
    """Límites de riesgo y capital calculados para la cuenta."""
    portfolio_value: Decimal
    buying_power: Decimal
    max_risk_pct: Decimal  # Por defecto 5% (0.05)
    max_single_trade_risk: Decimal  # Máximo $ a arriesgar por trade (5% del portfolio_value)
    max_portfolio_risk_pct: Decimal  # Por defecto 25% (0.25)
    max_total_options_allocation: Decimal  # Máxima asignación acumulada en opciones
    effective_trade_budget: Decimal  # min(max_single_trade_risk, buying_power, cash)


@dataclass(frozen=True)
class AccountHealth:
    """Resultado del chequeo de salud y viabilidad operativa de la cuenta."""
    is_healthy: bool
    can_trade: bool
    warnings: list[str] = field(default_factory=list)
    critical_errors: list[str] = field(default_factory=list)


# ==========================================
# Funciones Core del Módulo
# ==========================================

def get_trading_client(
    api_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    paper: bool = True,
) -> TradingClient:
    """
    Inicializa y retorna el cliente de Trading de Alpaca.
    Busca credenciales en parámetros o en variables de entorno.
    """
    load_dotenv()
    key = api_key or os.getenv("APCA_API_KEY_ID") or os.getenv("API_KEY")
    secret = secret_key or os.getenv("APCA_API_SECRET_KEY") or os.getenv("SECRET_KEY")

    if not key or not secret:
        raise AccountAuthError(
            "Credenciales de Alpaca no encontradas. Define API_KEY y SECRET_KEY en .env"
        )

    return TradingClient(api_key=key, secret_key=secret, paper=paper)


def get_account_snapshot(client: Optional[Any] = None) -> AccountSnapshot:
    """
    Obtiene el snapshot actual de la cuenta en Alpaca utilizando AlpacaGateway
    (eliminando llamadas directas ad-hoc REST de TradingClient).
    Mantiene compatibilidad con clientes mock inyectados en tests unitarios.
    """
    if client is None:
        try:
            from src.execution.mcp_gateway import AlpacaGateway
            gateway = AlpacaGateway()
            return gateway.get_account()
        except AccountError:
            raise
        except Exception as exc:
            raise AccountConnectionError(f"Error al obtener información de cuenta vía AlpacaGateway: {exc}") from exc

    # Si se pasó un cliente explícito (AlpacaGateway, TradingClient o Mock)
    try:
        from src.execution.mcp_gateway import AlpacaGateway
        if isinstance(client, AlpacaGateway):
            return client.get_account()
    except ImportError:
        pass

    try:
        alpaca_acc = client.get_account()
        if isinstance(alpaca_acc, AccountSnapshot):
            return alpaca_acc
        return AccountSnapshot.from_alpaca_account(alpaca_acc)
    except AccountError:
        raise
    except Exception as exc:
        raise AccountConnectionError(f"Error al obtener información de cuenta: {exc}") from exc


@dataclass(frozen=True)
class MarketClockInfo:
    """Información del reloj y horario oficial de mercado de Alpaca."""
    is_open: bool
    next_open: str
    next_close: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_open": self.is_open,
            "next_open": self.next_open,
            "next_close": self.next_close,
            "timestamp": self.timestamp,
        }


# Alias de MarketClockInfo para cumplimiento con Interface Contract
MarketClock = MarketClockInfo


def get_market_clock(client: Optional[Any] = None) -> MarketClockInfo:
    """
    Consulta el estado en vivo del reloj del mercado en Alpaca a través de AlpacaGateway.
    Mantiene compatibilidad con clientes mock inyectados en tests unitarios.
    """
    if client is None:
        try:
            from src.execution.mcp_gateway import AlpacaGateway
            gateway = AlpacaGateway()
            return gateway.get_clock()
        except Exception:
            return MarketClockInfo(
                is_open=False,
                next_open="09:30 AM EST",
                next_close="04:00 PM EST",
                timestamp="",
            )

    try:
        from src.execution.mcp_gateway import AlpacaGateway
        if isinstance(client, AlpacaGateway):
            return client.get_clock()
    except ImportError:
        pass

    try:
        clock = client.get_clock()
        if isinstance(clock, MarketClockInfo):
            return clock
        return MarketClockInfo(
            is_open=bool(getattr(clock, "is_open", False)),
            next_open=str(getattr(clock, "next_open", "")),
            next_close=str(getattr(clock, "next_close", "")),
            timestamp=str(getattr(clock, "timestamp", "")),
        )
    except Exception:
        # Fallback informativo si no se puede consultar el reloj
        return MarketClockInfo(
            is_open=False,
            next_open="09:30 AM EST",
            next_close="04:00 PM EST",
            timestamp="",
        )



def calculate_trade_limits(
    snapshot: AccountSnapshot,
    max_risk_pct: Decimal = Decimal("0.05"),
    max_portfolio_risk_pct: Decimal = Decimal("0.25"),
) -> AccountLimits:
    """
    Calcula los límites de capital y presupuesto seguro para operar opciones.
    
    Regla del 5%:
    - max_single_trade_risk = portfolio_value * max_risk_pct (ej. $100,000 * 0.05 = $5,000).
    - effective_trade_budget = min(max_single_trade_risk, buying_power, cash).
    """
    if max_risk_pct <= Decimal("0") or max_risk_pct > Decimal("1"):
        raise ValueError("max_risk_pct debe estar entre 0.0 y 1.0")

    portfolio_val = max(snapshot.portfolio_value, Decimal("0.0"))
    buying_power = max(snapshot.buying_power, Decimal("0.0"))
    cash = max(snapshot.cash, Decimal("0.0"))

    max_single_trade_risk = (portfolio_val * max_risk_pct).quantize(Decimal("0.01"))
    max_total_options_allocation = (portfolio_val * max_portfolio_risk_pct).quantize(Decimal("0.01"))

    # El presupuesto efectivo para compra de opciones no puede superar el buying power ni el cash disponible
    effective_budget = max(Decimal("0.0"), min(max_single_trade_risk, buying_power, cash))

    return AccountLimits(
        portfolio_value=portfolio_val,
        buying_power=buying_power,
        max_risk_pct=max_risk_pct,
        max_single_trade_risk=max_single_trade_risk,
        max_portfolio_risk_pct=max_portfolio_risk_pct,
        max_total_options_allocation=max_total_options_allocation,
        effective_trade_budget=effective_budget,
    )


def check_account_health(snapshot: AccountSnapshot) -> AccountHealth:
    """
    Verifica el estado de salud operativa de la cuenta para detectar anomalías antes de operar.
    """
    critical_errors: list[str] = []
    warnings: list[str] = []

    # Verificaciones Críticas (Bloquean trading)
    if snapshot.is_frozen:
        critical_errors.append("La cuenta está CONGELADA/BLOQUEADA en Alpaca.")

    if not snapshot.is_active:
        critical_errors.append("La cuenta NO está activa.")

    if snapshot.portfolio_value <= Decimal("0.0"):
        critical_errors.append("El valor de la cartera es cero o negativo.")

    if snapshot.buying_power <= Decimal("0.0"):
        critical_errors.append("No hay Buying Power disponible ($0.00).")

    # Verificaciones de Margen y Riesgo
    if snapshot.maintenance_margin > Decimal("0.0") and snapshot.equity > Decimal("0.0"):
        if snapshot.maintenance_margin >= snapshot.equity:
            critical_errors.append(
                f"Peligro de Margin Call: Margen de Mantenimiento (${snapshot.maintenance_margin}) "
                f"supera o iguala al Equity (${snapshot.equity})."
            )
        elif snapshot.maintenance_margin >= (snapshot.equity * Decimal("0.85")):
            warnings.append(
                f"Alerta de apalancamiento: Margen de Mantenimiento al 85%+ del Equity."
            )

    # Verificación de Pattern Day Trader
    if not snapshot.is_daytrader and snapshot.daytrading_count >= 3:
        warnings.append(
            f"Advertencia PDT: Se han realizado {snapshot.daytrading_count} day trades. "
            f"Un trade adicional activará la restricción de Pattern Day Trader."
        )

    can_trade = len(critical_errors) == 0
    is_healthy = can_trade and len(warnings) == 0

    return AccountHealth(
        is_healthy=is_healthy,
        can_trade=can_trade,
        warnings=warnings,
        critical_errors=critical_errors,
    )


def validate_trade_cost(cost: Decimal, limits: AccountLimits) -> tuple[bool, str]:
    """
    Valida si el costo total de un contrato/trade de opciones está dentro de los límites permitidos.
    
    Retorna:
    - (True, "Aprobado") si cumple todas las restricciones.
    - (False, "Motivo del rechazo") si excede el límite del 5% o el presupuesto disponible.
    """
    if cost <= Decimal("0.0"):
        return False, "El costo del trade debe ser mayor a $0.00"

    if cost > limits.max_single_trade_risk:
        return (
            False,
            f"El costo (${cost}) excede el límite máximo del {limits.max_risk_pct * 100}% "
            f"por trade (${limits.max_single_trade_risk}).",
        )

    if cost > limits.effective_trade_budget:
        return (
            False,
            f"El costo (${cost}) excede el presupuesto efectivo disponible (${limits.effective_trade_budget}) "
            f"basado en Buying Power y Cash.",
        )

    return True, f"Trade aprobado dentro del límite del {limits.max_risk_pct * 100}% (${cost} <= ${limits.effective_trade_budget})"


# ==========================================
# Ejecución Standalone / Demostración
# ==========================================

if __name__ == "__main__":
    print("--- Verificando Feature 1: Account & Limits Engine ---")
    try:
        snapshot = get_account_snapshot()
        print(f"Cuenta ID: {snapshot.account_id}")
        print(f"Portfolio Value: ${snapshot.portfolio_value}")
        print(f"Cash: ${snapshot.cash}")
        print(f"Buying Power: ${snapshot.buying_power}")
        
        limits = calculate_trade_limits(snapshot)
        print(f"Límite Máximo por Trade (5%): ${limits.max_single_trade_risk}")
        print(f"Presupuesto Efectivo: ${limits.effective_trade_budget}")
        
        health = check_account_health(snapshot)
        print(f"¿Saludable?: {health.is_healthy} | ¿Puede Operar?: {health.can_trade}")
        if health.warnings:
            print(f"Advertencias: {health.warnings}")
        if health.critical_errors:
            print(f"Errores Críticos: {health.critical_errors}")
            
    except AccountAuthError as auth_err:
        print(f"[Aviso de Configuración] {auth_err}")
    except Exception as err:
        print(f"[Error] {err}")
