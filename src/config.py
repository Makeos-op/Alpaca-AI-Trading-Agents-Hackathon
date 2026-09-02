"""
Configuración global del sistema de trading autónomo de opciones en Alpaca.
Todas las constantes numéricas financieras están tipadas con Decimal para máxima precisión.
"""

from decimal import Decimal
from typing import Final

# ==========================================
# Universo de Inversión Inicial
# ==========================================

DEFAULT_UNIVERSE: Final[list[str]] = ["AAPL", "MSFT", "SPY", "QQQ", "NVDA"]

# ==========================================
# Criterios de Liquidez Mínima
# ==========================================

MIN_DAILY_VOLUME: Final[Decimal] = Decimal("1000000")  # Volumen promedio diario >= 1,000,000
MAX_BID_ASK_SPREAD_PCT: Final[Decimal] = Decimal("0.01")  # Bid/Ask Spread <= 1.00% del precio
MIN_OPTION_OPEN_INTEREST: Final[int] = 500  # Open Interest en contratos de opciones >= 500

# ==========================================
# Parámetros de Indicadores Técnicos
# ==========================================

SMA_PERIOD_SHORT: Final[int] = 20
SMA_PERIOD_MEDIUM: Final[int] = 50
SMA_PERIOD_LONG: Final[int] = 200
SMA_PERIODS: Final[list[int]] = [SMA_PERIOD_SHORT, SMA_PERIOD_MEDIUM, SMA_PERIOD_LONG]

RSI_PERIOD: Final[int] = 14
RSI_OVERBOUGHT: Final[Decimal] = Decimal("70.0")
RSI_OVERSOLD: Final[Decimal] = Decimal("30.0")

MACD_FAST_PERIOD: Final[int] = 12
MACD_SLOW_PERIOD: Final[int] = 26
MACD_SIGNAL_PERIOD: Final[int] = 9

ATR_PERIOD: Final[int] = 14

# ==========================================
# Parámetros de Opciones
# ==========================================

MIN_DTE: Final[int] = 1  # Días mínimos hasta el vencimiento
MAX_DTE: Final[int] = 30  # Días máximos hasta el vencimiento (corto plazo)
MAX_OPTION_SPREAD_PCT: Final[Decimal] = Decimal("0.05")  # Tolerancia máxima spread en opciones: 5%

# ==========================================
# Parámetros de Riesgo y Capital
# ==========================================

DEFAULT_MAX_RISK_PER_TRADE_PCT: Final[Decimal] = Decimal("0.05")  # Regla del 5% max risk
DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT: Final[Decimal] = Decimal("0.25")  # 25% max en opciones

