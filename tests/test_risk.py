"""
Pruebas Unitarias para Feature 5: Risk Engine & Pre-Trade Validation (FT-RSK-05).
"""

import unittest
from decimal import Decimal

from src.account import AccountSnapshot
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


class TestRiskEngine(unittest.TestCase):
    """Pruebas del motor de riesgo determinista y guardrails pre-trade."""

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),  # 5% regla
            max_portfolio_options_pct=Decimal("0.25"),  # 25% regla
        )

        # Cuenta estándar saludable de $100,000
        self.healthy_snapshot = AccountSnapshot(
            account_id="acc-test-risk",
            cash=Decimal("50000.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("50000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("100000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

        # Contrato de opción líquido y válido
        self.valid_contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",  # $220.00 por contrato
            volume=2000,
            open_interest=1500,
            delta="0.50",
            gamma="0.08",
            theta="-0.04",
            vega="0.12",
            implied_volatility="0.1850",
        )

    def test_approved_safe_trade(self):
        # 5 contratos x $2.20 x 100 = $1,100.00 (1.10% del portfolio, dentro del 5% = $5,000)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=5,
            strategy_name="BullishMomentumCall",
        )

        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("1100.00"))
        self.assertEqual(verdict.max_allowed_budget, Decimal("5000.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0110"))
        self.assertEqual(len(verdict.reasons), 0)
        self.assertEqual(verdict.recommended_quantity, 22)  # $5000 // $220 = 22

    def test_rejected_exceeds_5_percent_limit(self):
        # 25 contratos x $2.20 x 100 = $5,500.00 (> $5,000.00)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=25,
            strategy_name="AggressiveCall",
        )

        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("5500.00"))
        self.assertTrue(any("excede el límite del 5.0" in r for r in verdict.reasons))
        # Recomienda la cantidad segura de 22 contratos
        self.assertEqual(verdict.recommended_quantity, 22)

    def test_rejected_insufficient_cash_or_buying_power(self):
        # Cuenta con solo $500.00 de cash libre
        poor_snapshot = AccountSnapshot(
            account_id="poor-acc",
            cash=Decimal("500.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("500.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("99500.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

        # 4 contratos x $2.20 x 100 = $880.00 (> $500.00 efectivo)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=4,
            strategy_name="MomentumCall",
        )

        verdict = self.risk_engine.evaluate_trade(proposal, poor_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("presupuesto efectivo disponible" in r for r in verdict.reasons))
        self.assertEqual(verdict.recommended_quantity, 2)  # $500 // $220 = 2 contratos

    def test_rejected_frozen_account(self):
        frozen_snapshot = AccountSnapshot(
            account_id="frozen-acc",
            cash=Decimal("50000.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("50000.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("50000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("50000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=True,
        )

        proposal = TradeProposal(contract=self.valid_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, frozen_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("CONGELADA" in r for r in verdict.reasons))

    def test_rejected_illiquid_option_low_open_interest(self):
        illiquid_contract = OptionContract.create(
            symbol="LOW_OI_CONTRACT",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            open_interest=100,  # < 500
        )

        proposal = TradeProposal(contract=illiquid_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Open Interest" in r for r in verdict.reasons))

    def test_rejected_wide_spread_option(self):
        wide_contract = OptionContract.create(
            symbol="WIDE_SPREAD",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="1.00",
            ask_price="1.50",  # Spread 40% > 5%
            open_interest=1000,
        )

        proposal = TradeProposal(contract=wide_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Spread Bid/Ask excesivo" in r for r in verdict.reasons))

    def test_rejected_invalid_dte(self):
        # DTE = 0 (0DTE de alto riesgo de expiración)
        zero_dte = OptionContract.create(
            symbol="ZERO_DTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-02",
            dte=0,
            bid_price="2.00",
            ask_price="2.05",
            open_interest=1000,
        )
        proposal = TradeProposal(contract=zero_dte, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Horizonte DTE inválido" in r for r in verdict.reasons))

    def test_max_portfolio_options_exposure_cap(self):
        # Exposición actual ya en $24,000 (límite 25% = $25,000)
        # Nuevo trade = 10 contratos x $2.20 x 100 = $2,200 ($24,000 + $2,200 = $26,200 > $25,000)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=10,
            strategy_name="AddExposure",
        )

        verdict = self.risk_engine.evaluate_trade(
            proposal=proposal,
            snapshot=self.healthy_snapshot,
            current_options_exposure=Decimal("24000.00"),
        )
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("exposición acumulada en opciones" in r for r in verdict.reasons))

    def test_proposal_invalid_quantity_raises(self):
        with self.assertRaises(ValueError):
            TradeProposal(contract=self.valid_contract, quantity=0, strategy_name="Test")

    def test_verdict_to_dict_serialization(self):
        proposal = TradeProposal(contract=self.valid_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        data = verdict.to_dict()
        self.assertIsInstance(data, dict)
        self.assertTrue(data["is_approved"])
        self.assertIsInstance(data["trade_cost"], str)


if __name__ == "__main__":
    unittest.main()

