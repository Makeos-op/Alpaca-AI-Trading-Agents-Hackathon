"""
Agente Autónomo de Estrategia de Opciones (Feature 6: FT-AGT-06).

Sintetiza indicadores técnicos (SMA, RSI, MACD, ATR), selecciona contratos óptimos
en la cadena de opciones (DTE 1-30, Delta objetivo) y formula propuestas de trade estructuradas
para ser validadas por el Risk Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from src.indicators.technicals import TechnicalSnapshot, to_decimal
from src.options.chain_filter import filter_option_chain, find_atm_contract, find_target_delta_contract
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import TradeProposal


class SignalType(str, Enum):
    """Tipo de señal generada por el agente de estrategia."""
    BULLISH_CALL_MOMENTUM = "BULLISH_CALL_MOMENTUM"
    BEARISH_PUT_MOMENTUM = "BEARISH_PUT_MOMENTUM"
    NEUTRAL_HOLD = "NEUTRAL_HOLD"


@dataclass(frozen=True)
class TradingSignal:
    """Señal formal de trading generada por el agente."""
    ticker: str
    signal_type: SignalType
    confidence: Decimal  # Escala 0.00 a 1.00
    target_option_type: Optional[OptionType]
    target_delta: Decimal
    rationale: str
    technical_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "signal_type": self.signal_type.value,
            "confidence": str(self.confidence),
            "target_option_type": self.target_option_type.value if self.target_option_type else None,
            "target_delta": str(self.target_delta),
            "rationale": self.rationale,
            "technical_summary": self.technical_summary,
        }


class AutonomousStrategyAgent:
    """
    Agente cuantitativo autónomo que evalúa condiciones de mercado y selecciona opciones.
    """

    def __init__(
        self,
        strategy_name: str = "OptionsMomentumTrader",
        default_target_delta: Decimal = Decimal("0.50"),
    ):
        self.strategy_name = strategy_name
        self.default_target_delta = to_decimal(default_target_delta)

    def evaluate_signals(self, snapshot: TechnicalSnapshot) -> TradingSignal:
        """
        Analiza las variables técnicas del activo y genera una señal con razonamiento cuantitativo.
        
        Lógica:
        - BULLISH CALL: Tendencia alcista (Precio > SMA20 > SMA50) + MACD Histograma > 0 + RSI < 70 (no sobrecomprado).
        - BEARISH PUT: Tendencia bajista (Precio < SMA20 < SMA50) + MACD Histograma < 0 + RSI > 30 (no sobrevendido).
        - NEUTRAL HOLD: Si los indicadores son divergentes o el mercado está lateral.
        """
        reasons: list[str] = []
        score_bullish = 0
        score_bearish = 0

        # 1. Análisis de Tendencia de Medias Móviles
        if snapshot.trend_summary == "BULLISH":
            score_bullish += 2
            reasons.append("Tendencia alcista confirmada (Precio > SMA20 > SMA50).")
        elif snapshot.trend_summary == "BEARISH":
            score_bearish += 2
            reasons.append("Tendencia bajista confirmada (Precio < SMA20 < SMA50).")
        else:
            reasons.append("Estructura de medias móviles neutra/lateral.")

        # 2. Análisis de Momentum MACD
        if snapshot.macd is not None:
            if snapshot.macd.histogram > Decimal("0.0"):
                score_bullish += 1
                reasons.append(f"MACD con histograma positivo ({snapshot.macd.histogram}).")
            elif snapshot.macd.histogram < Decimal("0.0"):
                score_bearish += 1
                reasons.append(f"MACD con histograma negativo ({snapshot.macd.histogram}).")

        # 3. Análisis de RSI (Filtro de Sobrecompra / Sobreventa)
        if snapshot.rsi_14 is not None:
            if snapshot.rsi_condition == "OVERBOUGHT":
                reasons.append(f"RSI en sobrecompra ({snapshot.rsi_14} >= 70). Bloquea nuevas compras de Calls.")
                score_bullish = 0
            elif snapshot.rsi_condition == "OVERSOLD":
                reasons.append(f"RSI en sobreventa ({snapshot.rsi_14} <= 30). Bloquea nuevas compras de Puts.")
                score_bearish = 0
            else:
                reasons.append(f"RSI en zona neutral saludable ({snapshot.rsi_14}).")

        # 4. Determinación de Señal Final
        if score_bullish >= 3:
            confidence = Decimal("0.85")
            return TradingSignal(
                ticker=snapshot.ticker,
                signal_type=SignalType.BULLISH_CALL_MOMENTUM,
                confidence=confidence,
                target_option_type=OptionType.CALL,
                target_delta=self.default_target_delta,
                rationale="; ".join(reasons),
                technical_summary=snapshot.to_dict(),
            )
        elif score_bearish >= 3:
            confidence = Decimal("0.85")
            return TradingSignal(
                ticker=snapshot.ticker,
                signal_type=SignalType.BEARISH_PUT_MOMENTUM,
                confidence=confidence,
                target_option_type=OptionType.PUT,
                target_delta=-self.default_target_delta,
                rationale="; ".join(reasons),
                technical_summary=snapshot.to_dict(),
            )
        else:
            return TradingSignal(
                ticker=snapshot.ticker,
                signal_type=SignalType.NEUTRAL_HOLD,
                confidence=Decimal("0.50"),
                target_option_type=None,
                target_delta=Decimal("0.0"),
                rationale="; ".join(reasons) or "Sin señal clara de entrada.",
                technical_summary=snapshot.to_dict(),
            )

    def select_best_contract(
        self,
        signal: TradingSignal,
        option_chain: list[OptionContract],
        underlying_price: Decimal,
    ) -> Optional[OptionContract]:
        """
        Filtra la cadena y selecciona el contrato más alineado con la señal del agente.
        """
        if signal.signal_type == SignalType.NEUTRAL_HOLD or signal.target_option_type is None:
            return None

        # 1. Aplicar filtros cuantitativos de calidad y horizonte
        valid_chain = filter_option_chain(option_chain)
        if not valid_chain:
            return None

        # 2. Buscar contrato por Delta objetivo o ATM
        if signal.target_delta != Decimal("0.0"):
            best_contract = find_target_delta_contract(
                contracts=valid_chain,
                contract_type=signal.target_option_type,
                target_delta=signal.target_delta,
            )
        else:
            best_contract = find_atm_contract(
                contracts=valid_chain,
                contract_type=signal.target_option_type,
                underlying_price=underlying_price,
            )

        return best_contract

    def propose_trade(
        self,
        signal: TradingSignal,
        selected_contract: OptionContract,
        quantity: int = 1,
    ) -> TradeProposal:
        """
        Formula la propuesta estructurada de trade para el Risk Engine.
        """
        return TradeProposal(
            contract=selected_contract,
            quantity=max(1, quantity),
            strategy_name=self.strategy_name,
            action="BUY",
        )

