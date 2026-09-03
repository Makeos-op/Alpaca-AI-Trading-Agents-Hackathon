"""
Pruebas Unitarias para Feature 6: Autonomous Strategy Agent (FT-AGT-06).
"""

import unittest
from decimal import Decimal

from src.agents.strategy_agent import AutonomousStrategyAgent, SignalType, TradingSignal
from src.indicators.technicals import MACDResult, PriceBar, TechnicalSnapshot
from src.options.models import OptionContract, OptionType


class TestAutonomousStrategyAgent(unittest.TestCase):
    """Pruebas del agente autónomo de toma de decisiones de opciones."""

    def setUp(self):
        self.agent = AutonomousStrategyAgent(strategy_name="TestOptionsAgent")

        self.sample_chain = [
            OptionContract.create(
                symbol="SPY260930C00500000",
                underlying_symbol="SPY",
                contract_type=OptionType.CALL,
                strike_price="500.00",
                expiration_date="2026-09-30",
                dte=20,
                bid_price="2.10",
                ask_price="2.20",
                open_interest=1500,
                delta="0.50",
            ),
            OptionContract.create(
                symbol="SPY260930P00500000",
                underlying_symbol="SPY",
                contract_type=OptionType.PUT,
                strike_price="500.00",
                expiration_date="2026-09-30",
                dte=20,
                bid_price="2.10",
                ask_price="2.20",
                open_interest=1500,
                delta="-0.50",
            ),
        ]

    def test_bullish_signal_generation(self):
        bullish_snap = TechnicalSnapshot(
            ticker="SPY",
            current_price=Decimal("505.00"),
            sma_20=Decimal("500.00"),
            sma_50=Decimal("495.00"),
            rsi_14=Decimal("58.00"),
            macd=MACDResult(
                macd_line=Decimal("1.50"),
                signal_line=Decimal("1.00"),
                histogram=Decimal("0.50"),
            ),
            trend_summary="BULLISH",
            rsi_condition="NEUTRAL",
        )

        signal = self.agent.evaluate_signals(bullish_snap)
        self.assertEqual(signal.signal_type, SignalType.BULLISH_CALL_MOMENTUM)
        self.assertEqual(signal.target_option_type, OptionType.CALL)
        self.assertGreater(signal.confidence, Decimal("0.80"))

        # Selección de mejor contrato Call
        best_contract = self.agent.select_best_contract(signal, self.sample_chain, Decimal("505.00"))
        self.assertIsNotNone(best_contract)
        self.assertEqual(best_contract.contract_type, OptionType.CALL)

        # Formulación de propuesta
        proposal = self.agent.propose_trade(signal, best_contract, quantity=2)
        self.assertEqual(proposal.quantity, 2)
        self.assertEqual(proposal.action, "BUY")

    def test_bearish_signal_generation(self):
        bearish_snap = TechnicalSnapshot(
            ticker="SPY",
            current_price=Decimal("490.00"),
            sma_20=Decimal("495.00"),
            sma_50=Decimal("500.00"),
            rsi_14=Decimal("42.00"),
            macd=MACDResult(
                macd_line=Decimal("-1.50"),
                signal_line=Decimal("-1.00"),
                histogram=Decimal("-0.50"),
            ),
            trend_summary="BEARISH",
            rsi_condition="NEUTRAL",
        )

        signal = self.agent.evaluate_signals(bearish_snap)
        self.assertEqual(signal.signal_type, SignalType.BEARISH_PUT_MOMENTUM)
        self.assertEqual(signal.target_option_type, OptionType.PUT)

        best_contract = self.agent.select_best_contract(signal, self.sample_chain, Decimal("490.00"))
        self.assertIsNotNone(best_contract)
        self.assertEqual(best_contract.contract_type, OptionType.PUT)

    def test_neutral_hold_signal(self):
        neutral_snap = TechnicalSnapshot(
            ticker="SPY",
            current_price=Decimal("500.00"),
            trend_summary="NEUTRAL",
            rsi_condition="NEUTRAL",
        )

        signal = self.agent.evaluate_signals(neutral_snap)
        self.assertEqual(signal.signal_type, SignalType.NEUTRAL_HOLD)
        self.assertIsNone(signal.target_option_type)

        best_contract = self.agent.select_best_contract(signal, self.sample_chain, Decimal("500.00"))
        self.assertIsNone(best_contract)

    def test_overbought_blocks_call_signal(self):
        # Aunque la tendencia sea BULLISH, RSI en sobrecompra bloquea compras de Calls
        overbought_snap = TechnicalSnapshot(
            ticker="SPY",
            current_price=Decimal("510.00"),
            sma_20=Decimal("500.00"),
            sma_50=Decimal("490.00"),
            rsi_14=Decimal("78.00"),  # > 70
            trend_summary="BULLISH",
            rsi_condition="OVERBOUGHT",
        )

        signal = self.agent.evaluate_signals(overbought_snap)
        self.assertEqual(signal.signal_type, SignalType.NEUTRAL_HOLD)
        self.assertIn("sobrecompra", signal.rationale)


if __name__ == "__main__":
    unittest.main()

