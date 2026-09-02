"""
Modelos de Datos para Contratos y Griegas de Opciones (Feature 4: FT-OPT-04).
Utiliza estrictamente Decimal para strikes, primas, spreads y griegas.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

from src.indicators.technicals import to_decimal


class OptionType(str, Enum):
    """Tipo de contrato de opción."""
    CALL = "CALL"
    PUT = "PUT"


class Moneyness(str, Enum):
    """Posición relativa respecto al precio del subyacente (Moneyness)."""
    ITM = "ITM"  # In-The-Money
    ATM = "ATM"  # At-The-Money
    OTM = "OTM"  # Out-Of-The-Money


class IVRegime(str, Enum):
    """Régimen de Volatilidad Implícita (IV)."""
    LOW = "LOW"            # IV < 20%
    MODERATE = "MODERATE"  # 20% <= IV <= 40%
    HIGH = "HIGH"          # IV > 40%


@dataclass(frozen=True)
class OptionGreeks:
    """Griegas y métricas de volatilidad con precisión Decimal."""
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    implied_volatility: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "delta": str(self.delta),
            "gamma": str(self.gamma),
            "theta": str(self.theta),
            "vega": str(self.vega),
            "implied_volatility": str(self.implied_volatility),
        }


@dataclass(frozen=True)
class OptionContract:
    """Representación inmutable y tipada de un contrato de opción."""
    symbol: str
    underlying_symbol: str
    contract_type: OptionType
    strike_price: Decimal
    expiration_date: str
    dte: int
    bid_price: Decimal
    ask_price: Decimal
    mid_price: Decimal
    bid_ask_spread_pct: Decimal
    volume: int
    open_interest: int
    greeks: OptionGreeks
    moneyness: Moneyness
    is_liquid: bool = True

    @classmethod
    def create(
        cls,
        symbol: str,
        underlying_symbol: str,
        contract_type: str | OptionType,
        strike_price: Any,
        expiration_date: str,
        dte: int,
        bid_price: Any,
        ask_price: Any,
        volume: int = 0,
        open_interest: int = 0,
        delta: Any = "0.0",
        gamma: Any = "0.0",
        theta: Any = "0.0",
        vega: Any = "0.0",
        implied_volatility: Any = "0.0",
        moneyness: str | Moneyness = Moneyness.ATM,
    ) -> OptionContract:
        """Construye y valida un OptionContract calculando Mid Price y Spread con Decimal."""
        c_type = OptionType(contract_type) if isinstance(contract_type, str) else contract_type
        m_type = Moneyness(moneyness) if isinstance(moneyness, str) else moneyness

        strike = to_decimal(strike_price)
        bid = to_decimal(bid_price)
        ask = to_decimal(ask_price)

        mid = (bid + ask) / Decimal("2.0")
        
        if mid > Decimal("0.0"):
            spread_pct = ((ask - bid) / mid).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        else:
            spread_pct = Decimal("1.0")

        greeks_obj = OptionGreeks(
            delta=to_decimal(delta),
            gamma=to_decimal(gamma),
            theta=to_decimal(theta),
            vega=to_decimal(vega),
            implied_volatility=to_decimal(implied_volatility),
        )

        return cls(
            symbol=symbol,
            underlying_symbol=underlying_symbol,
            contract_type=c_type,
            strike_price=strike,
            expiration_date=expiration_date,
            dte=int(dte),
            bid_price=bid,
            ask_price=ask,
            mid_price=mid,
            bid_ask_spread_pct=spread_pct,
            volume=int(volume or 0),
            open_interest=int(open_interest or 0),
            greeks=greeks_obj,
            moneyness=m_type,
            is_liquid=True,
        )

    def calculate_trade_cost(self, contracts: int = 1, use_ask: bool = True) -> Decimal:
        """Calcula el costo total en dólares de comprar N contratos (1 contrato = 100 acciones)."""
        if contracts <= 0:
            return Decimal("0.0")
        price = self.ask_price if use_ask and self.ask_price > Decimal("0.0") else self.mid_price
        multiplier = Decimal("100")
        contracts_dec = Decimal(str(contracts))
        total_cost = (price * multiplier * contracts_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return total_cost

    def to_dict(self) -> dict[str, Any]:
        """Serializa el contrato a formato JSON."""
        return {
            "symbol": self.symbol,
            "underlying_symbol": self.underlying_symbol,
            "contract_type": self.contract_type.value,
            "strike_price": str(self.strike_price),
            "expiration_date": self.expiration_date,
            "dte": self.dte,
            "bid_price": str(self.bid_price),
            "ask_price": str(self.ask_price),
            "mid_price": str(self.mid_price),
            "bid_ask_spread_pct": str(self.bid_ask_spread_pct),
            "volume": self.volume,
            "open_interest": self.open_interest,
            "greeks": self.greeks.to_dict(),
            "moneyness": self.moneyness.value,
            "is_liquid": self.is_liquid,
        }

