"""
Módulo de Ingestión de Datos de Mercado y Screener de Liquidez.
Utiliza estrictamente Decimal para precios, volúmenes y porcentajes de spread.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from dotenv import load_dotenv

from src.config import (
    DEFAULT_UNIVERSE,
    MAX_BID_ASK_SPREAD_PCT,
    MIN_DAILY_VOLUME,
    MIN_OPTION_OPEN_INTEREST,
)
from src.indicators.technicals import PriceBar, to_decimal


# ==========================================
# Modelos de Screener de Liquidez
# ==========================================

@dataclass(frozen=True)
class LiquidityScore:
    """Evaluación cuantitativa de liquidez de un activo (Escala 1-5 Estrellas)."""
    ticker: str
    daily_volume: Decimal
    bid_price: Decimal
    ask_price: Decimal
    bid_ask_spread_pct: Decimal
    option_open_interest: int
    stars: int
    is_tradable: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "daily_volume": str(self.daily_volume),
            "bid_price": str(self.bid_price),
            "ask_price": str(self.ask_price),
            "bid_ask_spread_pct": str(self.bid_ask_spread_pct),
            "option_open_interest": self.option_open_interest,
            "stars": self.stars,
            "is_tradable": self.is_tradable,
            "reasons": self.reasons,
        }


def screen_ticker_liquidity(
    ticker: str,
    daily_volume: Any,
    bid_price: Any,
    ask_price: Any,
    option_open_interest: int,
) -> LiquidityScore:
    """
    Evalúa la liquidez de un ticker según los criterios del Modelo Cuantitativo:
    - Volumen Diario >= 1,000,000 (+2 estrellas)
    - Bid/Ask Spread <= 1.00% (+2 estrellas)
    - Open Interest de Opciones >= 500 (+1 estrella)
    """
    volume = to_decimal(daily_volume)
    bid = to_decimal(bid_price)
    ask = to_decimal(ask_price)
    oi = int(option_open_interest or 0)

    stars = 0
    reasons: list[str] = []
    is_tradable = True

    # 1. Evaluación de Volumen
    if volume >= MIN_DAILY_VOLUME:
        stars += 2
    else:
        is_tradable = False
        reasons.append(f"Volumen insuficiente: {volume} < {MIN_DAILY_VOLUME}")

    # 2. Evaluación de Spread Bid/Ask
    mid_price = (bid + ask) / Decimal("2.0")
    if mid_price > Decimal("0.0"):
        spread_abs = ask - bid
        spread_pct = (spread_abs / mid_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    else:
        spread_pct = Decimal("1.0")

    if spread_pct <= MAX_BID_ASK_SPREAD_PCT and spread_pct >= Decimal("0.0"):
        stars += 2
    else:
        is_tradable = False
        reasons.append(
            f"Spread excesivo: {spread_pct * Decimal('100.0')}% > {MAX_BID_ASK_SPREAD_PCT * Decimal('100.0')}%"
        )

    # 3. Evaluación de Open Interest en Opciones
    if oi >= MIN_OPTION_OPEN_INTEREST:
        stars += 1
    else:
        is_tradable = False
        reasons.append(f"Open Interest en opciones bajo: {oi} < {MIN_OPTION_OPEN_INTEREST}")

    final_stars = max(1, min(5, stars))

    return LiquidityScore(
        ticker=ticker,
        daily_volume=volume,
        bid_price=bid,
        ask_price=ask,
        bid_ask_spread_pct=spread_pct,
        option_open_interest=oi,
        stars=final_stars,
        is_tradable=is_tradable,
        reasons=reasons,
    )


# ==========================================
# Cliente de Datos de Mercado
# ==========================================

class MarketDataService:
    """Servicio de obtención y normalización de datos de mercado con Alpaca SDK."""

    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        load_dotenv()
        self.api_key = api_key or os.getenv("APCA_API_KEY_ID") or os.getenv("API_KEY")
        self.secret_key = secret_key or os.getenv("APCA_API_SECRET_KEY") or os.getenv("SECRET_KEY")

    def parse_alpaca_bars(self, alpaca_bars: list[Any]) -> list[PriceBar]:
        """Convierte una lista de barras de Alpaca en PriceBars tipados con Decimal."""
        parsed_bars: list[PriceBar] = []
        for bar in alpaca_bars:
            parsed_bars.append(
                PriceBar.create(
                    open_p=getattr(bar, "open", 0),
                    high_p=getattr(bar, "high", 0),
                    low_p=getattr(bar, "low", 0),
                    close_p=getattr(bar, "close", 0),
                    volume_p=getattr(bar, "volume", 0),
                    timestamp=str(getattr(bar, "timestamp", "")),
                )
            )
        return parsed_bars

    def screen_universe(
        self,
        market_stats: dict[str, dict[str, Any]],
        universe: Optional[list[str]] = None,
    ) -> dict[str, LiquidityScore]:
        """Ejecuta el screener de liquidez sobre el universo de activos."""
        target_universe = universe or DEFAULT_UNIVERSE
        results: dict[str, LiquidityScore] = {}

        for ticker in target_universe:
            stats = market_stats.get(ticker, {})
            score = screen_ticker_liquidity(
                ticker=ticker,
                daily_volume=stats.get("volume", 0),
                bid_price=stats.get("bid", 0),
                ask_price=stats.get("ask", 0),
                option_open_interest=stats.get("open_interest", 0),
            )
            results[ticker] = score

        return results

