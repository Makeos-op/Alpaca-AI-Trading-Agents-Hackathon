"""
Motor de Indicadores Técnicos con Aritmética 100% Decimal.

Implementa:
- SMA (Medias Móviles Simples: 20, 50, 200).
- EMA (Medias Móviles Exponenciales con multiplicador exacto Decimal).
- RSI (Índice de Fuerza Relativa de 14 periodos con suavizado de Wilder).
- MACD (12, 26, 9: Línea MACD, Línea de Señal e Histograma).
- ATR (Average True Range de 14 periodos para volatilidad).
- Retornos diarios, Máximos y Mínimos de 52 semanas.
- Snapshot consolidado de indicadores técnicos (`TechnicalSnapshot`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from src.config import (
    ATR_PERIOD,
    MACD_FAST_PERIOD,
    MACD_SIGNAL_PERIOD,
    MACD_SLOW_PERIOD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SMA_PERIOD_LONG,
    SMA_PERIOD_MEDIUM,
    SMA_PERIOD_SHORT,
)


def to_decimal(val: Any, default: str = "0.0") -> Decimal:
    """Convierte cualquier valor a Decimal de forma segura sin pasar por float binario."""
    if val is None:
        return Decimal(default)
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


# ==========================================
# Modelos de Datos
# ==========================================

@dataclass(frozen=True)
class PriceBar:
    """Representación inmutable de una vela de precio OHLCV con Decimal."""
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp: str = ""

    @classmethod
    def create(
        cls,
        open_p: Any,
        high_p: Any,
        low_p: Any,
        close_p: Any,
        volume_p: Any,
        timestamp: str = "",
    ) -> PriceBar:
        return cls(
            open=to_decimal(open_p),
            high=to_decimal(high_p),
            low=to_decimal(low_p),
            close=to_decimal(close_p),
            volume=to_decimal(volume_p),
            timestamp=str(timestamp),
        )


@dataclass(frozen=True)
class MACDResult:
    """Resultado del cálculo MACD con precisión Decimal."""
    macd_line: Decimal
    signal_line: Decimal
    histogram: Decimal


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Snapshot consolidado de todos los indicadores técnicos de un activo."""
    ticker: str
    current_price: Decimal
    sma_20: Optional[Decimal] = None
    sma_50: Optional[Decimal] = None
    sma_200: Optional[Decimal] = None
    rsi_14: Optional[Decimal] = None
    macd: Optional[MACDResult] = None
    atr_14: Optional[Decimal] = None
    daily_return_pct: Optional[Decimal] = None
    high_52w: Optional[Decimal] = None
    low_52w: Optional[Decimal] = None
    trend_summary: str = "NEUTRAL"
    rsi_condition: str = "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        """Exporta el snapshot a un diccionario con valores en string Decimal."""
        data: dict[str, Any] = {
            "ticker": self.ticker,
            "current_price": str(self.current_price),
            "sma_20": str(self.sma_20) if self.sma_20 is not None else None,
            "sma_50": str(self.sma_50) if self.sma_50 is not None else None,
            "sma_200": str(self.sma_200) if self.sma_200 is not None else None,
            "rsi_14": str(self.rsi_14) if self.rsi_14 is not None else None,
            "atr_14": str(self.atr_14) if self.atr_14 is not None else None,
            "daily_return_pct": str(self.daily_return_pct) if self.daily_return_pct is not None else None,
            "high_52w": str(self.high_52w) if self.high_52w is not None else None,
            "low_52w": str(self.low_52w) if self.low_52w is not None else None,
            "trend_summary": self.trend_summary,
            "rsi_condition": self.rsi_condition,
        }
        if self.macd is not None:
            data["macd"] = {
                "macd_line": str(self.macd.macd_line),
                "signal_line": str(self.macd.signal_line),
                "histogram": str(self.macd.histogram),
            }
        else:
            data["macd"] = None
        return data


# ==========================================
# Funciones Matemáticas de Indicadores
# ==========================================

def calculate_sma(
    prices: list[Decimal],
    period: int,
    rounding_places: int = 4,
) -> Optional[Decimal]:
    """Calcula la Media Móvil Simple (SMA)."""
    if period <= 0 or len(prices) < period:
        return None

    recent_prices = prices[-period:]
    total = sum(recent_prices, Decimal("0.0"))
    sma = total / Decimal(str(period))
    quantizer = Decimal(f"1e-{rounding_places}")
    return sma.quantize(quantizer, rounding=ROUND_HALF_UP)


def calculate_ema(
    prices: list[Decimal],
    period: int,
    rounding_places: int = 6,
) -> list[Decimal]:
    """Calcula la serie EMA con factor alpha = 2 / (period + 1) en Decimal."""
    if period <= 0 or len(prices) < period:
        return []

    quantizer = Decimal(f"1e-{rounding_places}")
    alpha = Decimal("2.0") / Decimal(str(period + 1))
    one_minus_alpha = Decimal("1.0") - alpha

    initial_sum = sum(prices[:period], Decimal("0.0"))
    ema_prev = (initial_sum / Decimal(str(period))).quantize(quantizer, rounding=ROUND_HALF_UP)
    ema_series: list[Decimal] = [ema_prev]

    for price in prices[period:]:
        ema_current = (price * alpha + ema_prev * one_minus_alpha).quantize(quantizer, rounding=ROUND_HALF_UP)
        ema_series.append(ema_current)
        ema_prev = ema_current

    return ema_series


def calculate_rsi(
    closes: list[Decimal],
    period: int = RSI_PERIOD,
    rounding_places: int = 4,
) -> Optional[Decimal]:
    """Calcula RSI con método de suavizado de Wilder."""
    if period <= 0 or len(closes) < period + 1:
        return None

    quantizer = Decimal(f"1e-{rounding_places}")
    changes: list[Decimal] = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    initial_gains = [c if c > Decimal("0.0") else Decimal("0.0") for c in changes[:period]]
    initial_losses = [-c if c < Decimal("0.0") else Decimal("0.0") for c in changes[:period]]

    avg_gain = sum(initial_gains, Decimal("0.0")) / Decimal(str(period))
    avg_loss = sum(initial_losses, Decimal("0.0")) / Decimal(str(period))

    period_minus_one = Decimal(str(period - 1))
    period_dec = Decimal(str(period))

    for change in changes[period:]:
        gain = change if change > Decimal("0.0") else Decimal("0.0")
        loss = -change if change < Decimal("0.0") else Decimal("0.0")

        avg_gain = (avg_gain * period_minus_one + gain) / period_dec
        avg_loss = (avg_loss * period_minus_one + loss) / period_dec

    if avg_loss == Decimal("0.0"):
        return Decimal("100.0").quantize(quantizer, rounding=ROUND_HALF_UP)
    if avg_gain == Decimal("0.0"):
        return Decimal("0.0").quantize(quantizer, rounding=ROUND_HALF_UP)

    rs = avg_gain / avg_loss
    rsi = Decimal("100.0") - (Decimal("100.0") / (Decimal("1.0") + rs))
    return rsi.quantize(quantizer, rounding=ROUND_HALF_UP)


def calculate_macd(
    closes: list[Decimal],
    fast: int = MACD_FAST_PERIOD,
    slow: int = MACD_SLOW_PERIOD,
    signal: int = MACD_SIGNAL_PERIOD,
    rounding_places: int = 4,
) -> Optional[MACDResult]:
    """Calcula MACD, Línea Signal e Histograma."""
    if slow <= fast or len(closes) < slow + signal:
        return None

    fast_emas = calculate_ema(closes, fast, rounding_places=6)
    slow_emas = calculate_ema(closes, slow, rounding_places=6)

    offset = len(fast_emas) - len(slow_emas)
    macd_line_series: list[Decimal] = [
        fast_emas[offset + i] - slow_emas[i] for i in range(len(slow_emas))
    ]

    if len(macd_line_series) < signal:
        return None

    signal_line_series = calculate_ema(macd_line_series, signal, rounding_places=6)
    if not signal_line_series:
        return None

    latest_macd = macd_line_series[-1]
    latest_signal = signal_line_series[-1]
    latest_histogram = latest_macd - latest_signal

    quantizer = Decimal(f"1e-{rounding_places}")
    return MACDResult(
        macd_line=latest_macd.quantize(quantizer, rounding=ROUND_HALF_UP),
        signal_line=latest_signal.quantize(quantizer, rounding=ROUND_HALF_UP),
        histogram=latest_histogram.quantize(quantizer, rounding=ROUND_HALF_UP),
    )


def calculate_atr(
    bars: list[PriceBar],
    period: int = ATR_PERIOD,
    rounding_places: int = 4,
) -> Optional[Decimal]:
    """Calcula Average True Range (ATR) para volatilidad."""
    if period <= 0 or len(bars) < period + 1:
        return None

    quantizer = Decimal(f"1e-{rounding_places}")
    tr_series: list[Decimal] = []

    for i in range(1, len(bars)):
        current = bars[i]
        prev_close = bars[i - 1].close

        hl = current.high - current.low
        h_pc = abs(current.high - prev_close)
        l_pc = abs(current.low - prev_close)

        tr = max(hl, h_pc, l_pc)
        tr_series.append(tr)

    if len(tr_series) < period:
        return None

    atr = sum(tr_series[:period], Decimal("0.0")) / Decimal(str(period))
    period_minus_one = Decimal(str(period - 1))
    period_dec = Decimal(str(period))

    for tr in tr_series[period:]:
        atr = (atr * period_minus_one + tr) / period_dec

    return atr.quantize(quantizer, rounding=ROUND_HALF_UP)


def calculate_daily_return(
    bars: list[PriceBar],
    rounding_places: int = 4,
) -> Optional[Decimal]:
    """Calcula el retorno diario porcentual."""
    if len(bars) < 2:
        return None
    prev_close = bars[-2].close
    curr_close = bars[-1].close
    if prev_close == Decimal("0.0"):
        return None
    quantizer = Decimal(f"1e-{rounding_places}")
    ret = ((curr_close - prev_close) / prev_close) * Decimal("100.0")
    return ret.quantize(quantizer, rounding=ROUND_HALF_UP)


def calculate_52w_high_low(
    bars: list[PriceBar],
    max_bars: int = 252,
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Calcula el Máximo y Mínimo de 52 semanas."""
    if not bars:
        return None, None
    relevant_bars = bars[-max_bars:]
    high_52w = max(b.high for b in relevant_bars)
    low_52w = min(b.low for b in relevant_bars)
    return high_52w, low_52w


def compute_technical_snapshot(
    ticker: str,
    bars: list[PriceBar],
) -> TechnicalSnapshot:
    """Snapshot técnico consolidado."""
    if not bars:
        return TechnicalSnapshot(ticker=ticker, current_price=Decimal("0.0"))

    closes = [b.close for b in bars]
    current_price = closes[-1]

    sma_20 = calculate_sma(closes, SMA_PERIOD_SHORT)
    sma_50 = calculate_sma(closes, SMA_PERIOD_MEDIUM)
    sma_200 = calculate_sma(closes, SMA_PERIOD_LONG)
    rsi_14 = calculate_rsi(closes, RSI_PERIOD)
    macd = calculate_macd(closes)
    atr_14 = calculate_atr(bars, ATR_PERIOD)
    daily_return = calculate_daily_return(bars)
    high_52w, low_52w = calculate_52w_high_low(bars)

    trend = "NEUTRAL"
    if sma_20 is not None and sma_50 is not None:
        if current_price > sma_20 > sma_50:
            trend = "BULLISH"
        elif current_price < sma_20 < sma_50:
            trend = "BEARISH"

    rsi_cond = "NEUTRAL"
    if rsi_14 is not None:
        if rsi_14 >= RSI_OVERBOUGHT:
            rsi_cond = "OVERBOUGHT"
        elif rsi_14 <= RSI_OVERSOLD:
            rsi_cond = "OVERSOLD"

    return TechnicalSnapshot(
        ticker=ticker,
        current_price=current_price,
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        rsi_14=rsi_14,
        macd=macd,
        atr_14=atr_14,
        daily_return_pct=daily_return,
        high_52w=high_52w,
        low_52w=low_52w,
        trend_summary=trend,
        rsi_condition=rsi_cond,
    )

