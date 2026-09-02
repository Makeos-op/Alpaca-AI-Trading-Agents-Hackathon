"""
Motor Cuantitativo de Griegas, Moneyness y Volatilidad Implícita (Feature 4: FT-OPT-04).
Todo el cálculo y comparación se realiza con precisión Decimal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from src.indicators.technicals import to_decimal
from src.options.models import IVRegime, Moneyness, OptionGreeks, OptionType


def classify_moneyness(
    contract_type: OptionType,
    strike_price: Decimal,
    underlying_price: Decimal,
    delta: Optional[Decimal] = None,
) -> Moneyness:
    """Clasifica el estado Moneyness (ITM, ATM, OTM) de una opción."""
    if underlying_price <= Decimal("0.0") or strike_price <= Decimal("0.0"):
        return Moneyness.OTM

    # 1. Evaluación por Delta
    if delta is not None and delta != Decimal("0.0"):
        if contract_type == OptionType.CALL:
            if Decimal("0.40") <= delta <= Decimal("0.60"):
                return Moneyness.ATM
            elif delta > Decimal("0.60"):
                return Moneyness.ITM
            else:
                return Moneyness.OTM
        else:  # PUT
            if Decimal("-0.60") <= delta <= Decimal("-0.40"):
                return Moneyness.ATM
            elif delta < Decimal("-0.60"):
                return Moneyness.ITM
            else:
                return Moneyness.OTM

    # 2. Evaluación por proximidad de precio (Spot vs Strike)
    diff = abs(underlying_price - strike_price)
    proximity_pct = diff / underlying_price

    if proximity_pct <= Decimal("0.015"):
        return Moneyness.ATM

    if contract_type == OptionType.CALL:
        return Moneyness.ITM if underlying_price > strike_price else Moneyness.OTM
    else:
        return Moneyness.ITM if underlying_price < strike_price else Moneyness.OTM


def classify_iv_regime(implied_volatility: Decimal) -> IVRegime:
    """Clasifica el régimen de Volatilidad Implícita (IV)."""
    if implied_volatility < Decimal("0.20"):
        return IVRegime.LOW
    elif implied_volatility <= Decimal("0.40"):
        return IVRegime.MODERATE
    else:
        return IVRegime.HIGH


def parse_alpaca_greeks(greeks_data: Any) -> OptionGreeks:
    """Parsea las griegas devueltas por Alpaca a OptionGreeks con Decimal."""
    if greeks_data is None:
        return OptionGreeks(
            delta=Decimal("0.0"),
            gamma=Decimal("0.0"),
            theta=Decimal("0.0"),
            vega=Decimal("0.0"),
            implied_volatility=Decimal("0.0"),
        )

    if isinstance(greeks_data, dict):
        return OptionGreeks(
            delta=to_decimal(greeks_data.get("delta", 0)),
            gamma=to_decimal(greeks_data.get("gamma", 0)),
            theta=to_decimal(greeks_data.get("theta", 0)),
            vega=to_decimal(greeks_data.get("vega", 0)),
            implied_volatility=to_decimal(
                greeks_data.get("implied_volatility", greeks_data.get("iv", 0))
            ),
        )

    return OptionGreeks(
        delta=to_decimal(getattr(greeks_data, "delta", 0)),
        gamma=to_decimal(getattr(greeks_data, "gamma", 0)),
        theta=to_decimal(getattr(greeks_data, "theta", 0)),
        vega=to_decimal(getattr(greeks_data, "vega", 0)),
        implied_volatility=to_decimal(
            getattr(greeks_data, "implied_volatility", getattr(greeks_data, "iv", 0))
        ),
    )

