"""
Pruebas Unitarias Exhaustivas para el Motor de Riesgo Pre-Trade (Feature F2.1 - F2.5).
Valida determinísticamente los escenarios TC-RSK-01 a TC-RSK-17 per spec_report.md
y asegura precisión del 100% con Decimal y cero regresiones.
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.account import AccountSnapshot
from src.execution.alpaca_executor import OptionExecutor
from src.execution.trade_logger import TradeLogger
from src.options.models import OptionContract, OptionType
from src.risk.models import (
    RiskConfig,
    RiskReasonCode,
    RiskVerdict,
    TradeProposal,
)
from src.risk.risk_engine import RiskEngine


class TestRiskEngineScenarios(unittest.TestCase):
    """
    Suite completa de verificación de escenarios deterministas de riesgo (TC-RSK-01 a TC-RSK-17).
    """

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

        # Contrato de opción líquido y válido (benchmark de referencia)
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

    # --------------------------------------------------------------------------
    # TC-RSK-01: 5% Single Trade Violation
    # --------------------------------------------------------------------------
    def test_tc_rsk_01_exceeds_5_percent_single_trade_limit(self):
        """TC-RSK-01: Rechazo si el costo de un trade excede el 5% de la cartera ($5,000)."""
        ask_price = Decimal("2.50")
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.45",
            ask_price=ask_price,
            volume=1500,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        # 25 contratos x $2.50 x 100 = $6,250.00 > $5,000.00 (5% de $100k)
        proposal = TradeProposal(
            contract=contract,
            quantity=25,
            strategy_name="AggressiveCall",
        )

        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)
        self.assertIn(RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT, verdict.reason_codes)
        self.assertEqual(verdict.trade_cost, Decimal("6250.00"))
        self.assertEqual(verdict.max_allowed_budget, Decimal("5000.00"))
        # floor($5000 / $250) = 20 contratos
        self.assertEqual(verdict.recommended_quantity, 20)
        self.assertEqual(verdict.max_safe_quantity, 20)
        self.assertIn("trade_cost", verdict.audited_metrics)

    # --------------------------------------------------------------------------
    # TC-RSK-02: Effective Cash Depletion
    # --------------------------------------------------------------------------
    def test_tc_rsk_02_effective_cash_depletion(self):
        """TC-RSK-02: Rechazo si el costo excede el efectivo disponible aunque esté dentro del 5%."""
        low_cash_snapshot = AccountSnapshot(
            account_id="low-cash-acc",
            cash=Decimal("600.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("50000.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("99400.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("50000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

        # 4 contratos x $2.20 x 100 = $880.00 (> $600.00 cash disponible)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=4,
            strategy_name="MomentumCall",
        )

        verdict = self.risk_engine.evaluate_trade(proposal, low_cash_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_INSUFFICIENT_CASH)
        self.assertTrue(
            RiskReasonCode.ERR_INSUFFICIENT_CASH in verdict.reason_codes
            or RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER in verdict.reason_codes
        )
        # floor($600 / $220) = 2 contratos
        self.assertEqual(verdict.recommended_quantity, 2)
        self.assertEqual(verdict.max_safe_quantity, 2)

    # --------------------------------------------------------------------------
    # TC-RSK-03: Wide Bid-Ask Spread
    # --------------------------------------------------------------------------
    def test_tc_rsk_03_wide_bid_ask_spread(self):
        """TC-RSK-03: Rechazo si el spread bid-ask supera el 5.00%."""
        # Bid = $1.00, Ask = $1.40 -> Mid = $1.20, Spread = $0.40 / $1.20 = 33.33% > 5%
        wide_contract = OptionContract.create(
            symbol="WIDE_SPREAD",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="1.00",
            ask_price="1.40",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.25",
        )
        proposal = TradeProposal(contract=wide_contract, quantity=1, strategy_name="Test")

        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD)
        self.assertTrue(
            RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD in verdict.reason_codes
            or RiskReasonCode.ERR_SPREAD_EXCEEDS_MAX in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-04: Zero / Stale Bid-Ask / Crossed Quote
    # --------------------------------------------------------------------------
    def test_tc_rsk_04_crossed_or_zero_quote(self):
        """TC-RSK-04: Rechazo si las cotizaciones están cruzadas (Ask <= Bid) o cotización cero."""
        # Caso A: Bid = $0.00
        zero_bid_contract = OptionContract.create(
            symbol="ZERO_BID",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="0.00",
            ask_price="1.50",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.25",
        )
        verdict_zero = self.risk_engine.evaluate_trade(
            TradeProposal(contract=zero_bid_contract, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict_zero.is_approved)
        self.assertEqual(verdict_zero.reason_code, RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE)

        # Caso B: Mercado cruzado (Bid = $2.50 > Ask = $2.40)
        crossed_contract = OptionContract.create(
            symbol="CROSSED_QUOTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.50",
            ask_price="2.40",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.25",
        )
        verdict_crossed = self.risk_engine.evaluate_trade(
            TradeProposal(contract=crossed_contract, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict_crossed.is_approved)
        self.assertEqual(verdict_crossed.reason_code, RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE)

    # --------------------------------------------------------------------------
    # TC-RSK-05: Low Open Interest / Illiquid
    # --------------------------------------------------------------------------
    def test_tc_rsk_05_low_open_interest(self):
        """TC-RSK-05: Rechazo si el Open Interest es menor a 500 contratos."""
        illiquid_contract = OptionContract.create(
            symbol="LOW_OI",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=150,  # < 500
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=illiquid_contract, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_INSUFFICIENT_OPEN_INTEREST)
        self.assertTrue(
            RiskReasonCode.ERR_INSUFFICIENT_OPEN_INTEREST in verdict.reason_codes
            or RiskReasonCode.ERR_OPEN_INTEREST_BELOW_MIN in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-06: Zero / Low Volume Day
    # --------------------------------------------------------------------------
    def test_tc_rsk_06_low_volume(self):
        """TC-RSK-06: Rechazo si el volumen diario de contratos es menor a 100."""
        low_vol_contract = OptionContract.create(
            symbol="LOW_VOL",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=0,  # < 100
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=low_vol_contract, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_INSUFFICIENT_VOLUME)
        self.assertTrue(
            RiskReasonCode.ERR_INSUFFICIENT_VOLUME in verdict.reason_codes
            or RiskReasonCode.ERR_VOLUME_BELOW_MIN in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-07: 0-DTE Expiration Pin Risk
    # --------------------------------------------------------------------------
    def test_tc_rsk_07_zero_dte_pin_risk(self):
        """TC-RSK-07: Bloqueo estricto de opciones 0-DTE (expiración intradía)."""
        zero_dte = OptionContract.create(
            symbol="ZERO_DTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-03",
            dte=0,  # < 1
            bid_price="2.10",
            ask_price="2.20",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=zero_dte, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS)
        self.assertTrue(
            RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS in verdict.reason_codes
            or RiskReasonCode.ERR_DTE_BELOW_MIN in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-08: Far-Out DTE Expiration
    # --------------------------------------------------------------------------
    def test_tc_rsk_08_far_out_dte(self):
        """TC-RSK-08: Rechazo si el DTE es superior a 30 días."""
        far_dte = OptionContract.create(
            symbol="FAR_DTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-11-03",
            dte=60,  # > 30
            bid_price="2.10",
            ask_price="2.20",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=far_dte, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS)
        self.assertTrue(
            RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS in verdict.reason_codes
            or RiskReasonCode.ERR_DTE_ABOVE_MAX in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-09: Delta Out of Bounds (Call Deep OTM Lottery Ticket)
    # --------------------------------------------------------------------------
    def test_tc_rsk_09_call_delta_out_of_bounds(self):
        """TC-RSK-09: Rechazo si Call Delta es menor a 0.30 (especulación deep OTM)."""
        otm_call = OptionContract.create(
            symbol="OTM_CALL",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="550.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="0.41",
            ask_price="0.42",
            volume=1000,
            open_interest=2000,
            delta="0.15",  # < 0.30
            theta="-0.01",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=otm_call, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)
        self.assertIn(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS, verdict.reason_codes)

    # --------------------------------------------------------------------------
    # TC-RSK-10: Delta Out of Bounds (Put Deep ITM)
    # --------------------------------------------------------------------------
    def test_tc_rsk_10_put_delta_out_of_bounds(self):
        """TC-RSK-10: Rechazo si Put Delta es más negativo que -0.70 (deep ITM)."""
        deep_itm_put = OptionContract.create(
            symbol="ITM_PUT",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="550.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="50.00",
            ask_price="50.20",
            volume=1000,
            open_interest=2000,
            delta="-0.85",  # < -0.70
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=deep_itm_put, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)
        self.assertIn(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS, verdict.reason_codes)

    # --------------------------------------------------------------------------
    # TC-RSK-11: Excessive Theta Decay Rate
    # --------------------------------------------------------------------------
    def test_tc_rsk_11_excessive_theta_decay(self):
        """TC-RSK-11: Rechazo si la pérdida diaria por Theta supera el 5% del valor de la prima."""
        # Ask = $0.40, Theta = -0.04 -> 0.04 / 0.40 = 10.00% diario > 5.00%
        # Bid = $0.39, Ask = $0.40 -> Spread = 0.01 / 0.395 = 2.53% (<= 5.00%)
        bleeding_contract = OptionContract.create(
            symbol="THETA_BLEED",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="0.39",
            ask_price="0.40",
            volume=1000,
            open_interest=2000,
            delta="0.45",
            theta="-0.04",  # 10% diario
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=bleeding_contract, quantity=1, strategy_name="Test"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE)
        self.assertIn(RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE, verdict.reason_codes)

    # --------------------------------------------------------------------------
    # TC-RSK-12: Account Frozen / Restricted
    # --------------------------------------------------------------------------
    def test_tc_rsk_12_account_frozen(self):
        """TC-RSK-12: Rechazo automático si la cuenta está congelada o bloqueada."""
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
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=self.valid_contract, quantity=1, strategy_name="Test"),
            frozen_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED)
        self.assertTrue(
            RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED in verdict.reason_codes
            or RiskReasonCode.ERR_ACCOUNT_FROZEN in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-13: Margin Call Protection
    # --------------------------------------------------------------------------
    def test_tc_rsk_13_margin_call_protection(self):
        """TC-RSK-13: Rechazo si el margen de mantenimiento iguala o supera al equity."""
        margin_call_snapshot = AccountSnapshot(
            account_id="margin-call-acc",
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("50000.00"),
            buying_power=Decimal("5000.00"),
            equity=Decimal("50000.00"),
            long_market_value=Decimal("45000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("30000.00"),
            maintenance_margin=Decimal("55000.00"),  # > equity de $50,000
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=self.valid_contract, quantity=1, strategy_name="Test"),
            margin_call_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED)
        self.assertTrue(
            RiskReasonCode.ERR_MARGIN_CALL_RISK in verdict.reason_codes
            or RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-14: Cumulative Options Allocation Cap (25%)
    # --------------------------------------------------------------------------
    def test_tc_rsk_14_cumulative_options_cap(self):
        """TC-RSK-14: Rechazo si la suma acumulada en opciones superaría el 25% ($25,000)."""
        # Exposición actual = $24,000. Nuevo trade = 10 contratos x $2.20 x 100 = $2,200.
        # Total proyectado = $26,200 > $25,000.
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
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP)
        self.assertTrue(
            RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP in verdict.reason_codes
            or RiskReasonCode.ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT in verdict.reason_codes
        )

    # --------------------------------------------------------------------------
    # TC-RSK-15: Valid Approved Trade (Scan Mode)
    # --------------------------------------------------------------------------
    def test_tc_rsk_15_approved_valid_trade(self):
        """TC-RSK-15: Aprobación total de trade que satisface todos los guardrails de riesgo."""
        # 2 contratos x $2.20 x 100 = $440.00 (0.44% del portfolio, dentro del 5%)
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=2,
            strategy_name="BullishMomentumScan",
        )
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)
        self.assertEqual(len(verdict.reasons), 0)
        self.assertEqual(len(verdict.reason_codes), 0)
        self.assertEqual(verdict.trade_cost, Decimal("440.00"))
        self.assertEqual(verdict.max_allowed_budget, Decimal("5000.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0044"))
        self.assertEqual(verdict.recommended_quantity, 22)
        self.assertEqual(verdict.max_safe_quantity, 22)
        self.assertEqual(verdict.audited_metrics["recommended_quantity"], 22)

    # --------------------------------------------------------------------------
    # TC-RSK-16: Valid Trade Isolation / Dry-Run No-Op Guarantee
    # --------------------------------------------------------------------------
    def test_tc_rsk_16_dry_run_simulation_guarantee(self):
        """TC-RSK-16: Trade aprobado evaluado con éxito y métricas de auditoría completas."""
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=1,
            strategy_name="DryRunSafeStrategy",
        )
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("220.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0022"))
        self.assertIn("portfolio_value", verdict.audited_metrics)
        self.assertIn("projected_options_exposure", verdict.audited_metrics)

    # --------------------------------------------------------------------------
    # TC-RSK-17: Infrangible Broker Blocking / Rejection Safety Gate
    # --------------------------------------------------------------------------
    def test_tc_rsk_17_infrangible_blocking_prevents_broker_call(self):
        """TC-RSK-17: La capa de ejecución bloquea estrictamente la orden si RiskVerdict es False."""
        mock_client = MagicMock()
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = TradeLogger(log_file_path=Path(temp_dir) / "test_trades.jsonl")
            executor = OptionExecutor(trading_client=mock_client, logger=logger)

            # Trade rechazado por violar la regla del 5%
            proposal = TradeProposal(
                contract=self.valid_contract,
                quantity=30,  # $6,600 > $5,000
                strategy_name="OverleveragedTrade",
            )
            verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
            self.assertFalse(verdict.is_approved)

            # Ejecución debe ser bloqueada sin tocar el cliente del broker
            res = executor.execute_approved_trade(proposal, verdict)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "REJECTED")
            self.assertIn("Orden cancelada por el Risk Engine", res.error_message)

            # Invariante infranqueable: submit_order NUNCA es llamada
            mock_client.submit_order.assert_not_called()

            # Verificación de registro en bitácora
            history = logger.get_trade_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].event_type, "TRADE_REJECTED")
            self.assertFalse(history[0].is_approved)


class TestRiskEngineExtendedGuardrails(unittest.TestCase):
    """
    Pruebas adicionales de robustez, límites de griegas, serialización y contratos de llamada.
    """

    def setUp(self):
        self.risk_engine = RiskEngine()
        self.snapshot = AccountSnapshot(
            account_id="acc-ext",
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
            is_frozen=False,
        )

    def test_put_delta_valid_range(self):
        """Put Delta dentro del rango permitido [-0.70, -0.30] es aprobado."""
        valid_put = OptionContract.create(
            symbol="PUT_VALID",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
            delta="-0.50",  # Dentro de [-0.70, -0.30]
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=valid_put, quantity=1, strategy_name="PutHedger")
        verdict = self.risk_engine.evaluate_trade(proposal, self.snapshot)
        self.assertTrue(verdict.is_approved)

    def test_put_delta_otm_rejected(self):
        """Put Delta mayor a -0.30 (especulativo OTM) es rechazado."""
        otm_put = OptionContract.create(
            symbol="PUT_OTM",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="450.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="0.51",
            ask_price="0.52",
            volume=500,
            open_interest=1000,
            delta="-0.15",  # > -0.30
            theta="-0.01",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=otm_put, quantity=1, strategy_name="PutLottery")
        verdict = self.risk_engine.evaluate_trade(proposal, self.snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS)

    def test_iv_out_of_bounds_low_and_high(self):
        """IV menor a 0.05 o mayor a 1.00 es rechazado."""
        # IV demasiado bajo (< 0.05)
        low_iv_contract = OptionContract.create(
            symbol="LOW_IV",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.02",  # < 0.05
        )
        verdict_low = self.risk_engine.evaluate_trade(
            TradeProposal(contract=low_iv_contract, quantity=1, strategy_name="Test"),
            self.snapshot,
        )
        self.assertFalse(verdict_low.is_approved)
        self.assertEqual(verdict_low.reason_code, RiskReasonCode.ERR_IV_OUT_OF_BOUNDS)

        # IV demasiado alto (> 1.00)
        high_iv_contract = OptionContract.create(
            symbol="HIGH_IV",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="1.45",  # > 1.00
        )
        verdict_high = self.risk_engine.evaluate_trade(
            TradeProposal(contract=high_iv_contract, quantity=1, strategy_name="Test"),
            self.snapshot,
        )
        self.assertFalse(verdict_high.is_approved)
        self.assertEqual(verdict_high.reason_code, RiskReasonCode.ERR_IV_OUT_OF_BOUNDS)

    def test_absolute_spread_cap_exceeded(self):
        """Spread absoluto mayor a $0.50 es rechazado incluso si el porcentaje es bajo."""
        # Bid = $20.00, Ask = $20.70 -> Spread = $0.70 (> $0.50), Spread Pct = 0.70 / 20.35 = 3.44% (<= 5%)
        wide_abs_contract = OptionContract.create(
            symbol="WIDE_ABS_SPREAD",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="20.00",
            ask_price="20.70",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=wide_abs_contract, quantity=1, strategy_name="Test"),
            self.snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD)

    def test_custom_risk_config_injection(self):
        """RiskEngine respeta la inyección de una configuración personalizada RiskConfig."""
        custom_config = RiskConfig(
            max_risk_pct=Decimal("0.02"),  # Límite más estricto del 2%
            max_portfolio_options_pct=Decimal("0.10"),
            min_open_interest=200,
        )
        custom_engine = RiskEngine(config=custom_config)

        # 10 contratos x $2.20 x 100 = $2,200 (> 2% de $100k = $2,000)
        valid_contract = OptionContract.create(
            symbol="SPY_CUSTOM",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=300,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=valid_contract, quantity=10, strategy_name="Test")
        verdict = custom_engine.evaluate_trade(proposal, self.snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_allowed_budget, Decimal("2000.00"))

    def test_alternative_signature_calling_conventions(self):
        """Verifica compatibilidad con la firma de PROJECT.md (proposal, account, contract, underlying_price)."""
        valid_contract = OptionContract.create(
            symbol="SPY_SIG",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=valid_contract, quantity=1, strategy_name="Test")

        verdict = self.risk_engine.evaluate_trade(
            proposal=proposal,
            account=self.snapshot,
            contract=valid_contract,
            underlying_price=Decimal("500.00"),
        )
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)

    def test_proposal_invalid_quantity_raises(self):
        """TradeProposal lanza ValueError si la cantidad es menor o igual a 0."""
        valid_contract = OptionContract.create(
            symbol="SPY_QTY",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
        )
        with self.assertRaises(ValueError):
            TradeProposal(contract=valid_contract, quantity=0, strategy_name="Test")

    def test_verdict_to_dict_serialization(self):
        """RiskVerdict.to_dict exporta correctamente todos los campos a tipos primitivos."""
        valid_contract = OptionContract.create(
            symbol="SPY_SERIALIZE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=valid_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.snapshot)
        data = verdict.to_dict()

        self.assertIsInstance(data, dict)
        self.assertTrue(data["is_approved"])
        self.assertEqual(data["reason_code"], "APPROVED")
        self.assertIsInstance(data["trade_cost"], str)
        self.assertIsInstance(data["audited_metrics"], dict)
        self.assertEqual(data["max_safe_quantity"], verdict.max_safe_quantity)


class TestOriginalRiskEngine(unittest.TestCase):
    """Pruebas originales de regresión del motor de riesgo determinista."""

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )

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

        self.valid_contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            volume=2000,
            open_interest=1500,
            delta="0.50",
            gamma="0.08",
            theta="-0.04",
            vega="0.12",
            implied_volatility="0.1850",
        )

    def test_approved_safe_trade(self):
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
        self.assertEqual(verdict.recommended_quantity, 22)

    def test_rejected_exceeds_5_percent_limit(self):
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=25,
            strategy_name="AggressiveCall",
        )
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("5500.00"))
        self.assertTrue(any("excede el límite del 5.0" in r for r in verdict.reasons))
        self.assertEqual(verdict.recommended_quantity, 22)

    def test_rejected_insufficient_cash_or_buying_power(self):
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
        proposal = TradeProposal(
            contract=self.valid_contract,
            quantity=4,
            strategy_name="MomentumCall",
        )
        verdict = self.risk_engine.evaluate_trade(proposal, poor_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("presupuesto efectivo disponible" in r for r in verdict.reasons))
        self.assertEqual(verdict.recommended_quantity, 2)

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
            volume=500,
            open_interest=100,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
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
            ask_price="1.50",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=wide_contract, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Spread Bid/Ask excesivo" in r for r in verdict.reasons))

    def test_rejected_invalid_dte(self):
        zero_dte = OptionContract.create(
            symbol="ZERO_DTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-02",
            dte=0,
            bid_price="2.00",
            ask_price="2.05",
            volume=500,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=zero_dte, quantity=1, strategy_name="Test")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Horizonte DTE inválido" in r for r in verdict.reasons))

    def test_max_portfolio_options_exposure_cap(self):
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

    # ==========================================================================
    # Equity Risk Evaluation Tests (Multi-Asset Expansion)
    # ==========================================================================

    def test_equity_proposal_1x_multiplier_and_5_percent_limit_approved(self):
        """Verifica que el costo de acciones use multiplicador 1x y apruebe trades <= 5% ($5,000)."""
        # 10 acciones x $500.00 x 1 = $5,000.00 (exactamente 5% de $100,000)
        proposal = TradeProposal(
            symbol="SPY",
            quantity=10,
            asset_class="equity",
            price=Decimal("500.00"),
            ask_price=Decimal("500.00"),
            bid_price=Decimal("499.90"),
            strategy_name="ScalpEquity",
            action="BUY",
        )
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)
        self.assertEqual(verdict.trade_cost, Decimal("5000.00"))
        self.assertEqual(verdict.max_allowed_budget, Decimal("5000.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0500"))

    def test_equity_proposal_1x_multiplier_exceeds_5_percent_rejected(self):
        """Verifica que 11 acciones de $500 ($5,500 > $5,000) sea rechazado por regla del 5%."""
        # 11 acciones x $500.00 x 1 = $5,500.00 (> $5,000.00)
        proposal = TradeProposal(
            symbol="SPY",
            quantity=11,
            asset_class="equity",
            price=Decimal("500.00"),
            ask_price=Decimal("500.00"),
            bid_price=Decimal("499.90"),
            strategy_name="ScalpEquity",
            action="BUY",
        )
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)
        self.assertEqual(verdict.trade_cost, Decimal("5500.00"))
        self.assertEqual(verdict.recommended_quantity, 10)

    def test_equity_proposal_bypasses_greeks_and_dte_filters(self):
        """Verifica que las propuestas de acciones no requieran DTE, Delta, Theta ni Open Interest."""
        proposal = TradeProposal(
            symbol="AAPL",
            quantity=5,
            asset_class="equity",
            price=Decimal("220.00"),
            ask_price=Decimal("220.05"),
            bid_price=Decimal("220.00"),
            strategy_name="QuickTrade",
            action="BUY",
        )
        # No hay OptionContract, no hay griegas, ni DTE
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)
        # Verificar que no hay razones de rechazo relacionadas con opciones
        for r in verdict.reasons:
            self.assertNotIn("DTE", r)
            self.assertNotIn("Delta", r)
            self.assertNotIn("Theta", r)
            self.assertNotIn("Open Interest", r)

    def test_equity_proposal_bid_ask_spread_relative_excessive_rejected(self):
        """Verifica que un spread relativo > 5.00% en acciones sea rechazado."""
        # Ask $10.60, Bid $10.00 -> spread $0.60 / mid $10.30 = 5.83% > 5.00%
        proposal = TradeProposal(
            symbol="PENNY",
            quantity=10,
            asset_class="equity",
            price=Decimal("10.30"),
            ask_price=Decimal("10.60"),
            bid_price=Decimal("10.00"),
            strategy_name="TestSpread",
        )
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, verdict.reason_codes)

    def test_equity_proposal_bid_ask_spread_absolute_excessive_rejected(self):
        """Verifica que un spread absoluto > $0.50 en acciones sea rechazado."""
        # Ask $500.60, Bid $500.00 -> spread $0.60 > $0.50 (aunque relativo sea 0.12%)
        proposal = TradeProposal(
            symbol="SPY",
            quantity=1,
            asset_class="equity",
            price=Decimal("500.30"),
            ask_price=Decimal("500.60"),
            bid_price=Decimal("500.00"),
            strategy_name="TestSpread",
        )
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, verdict.reason_codes)

    def test_equity_proposal_crossed_quote_rejected(self):
        """Verifica que cotizaciones cruzadas (Ask < Bid) en acciones sean rechazadas."""
        proposal = TradeProposal(
            symbol="SPY",
            quantity=1,
            asset_class="equity",
            price=Decimal("500.00"),
            ask_price=Decimal("499.50"),
            bid_price=Decimal("500.50"),
            strategy_name="CrossedTest",
        )
        verdict = self.risk_engine.evaluate_proposal(proposal, self.healthy_snapshot)
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE, verdict.reason_codes)

    def test_equity_safe_quantity_calculation(self):
        """Verifica el cálculo de cantidad segura máxima para acciones vs opciones."""
        # Para acciones: presupuesto $5,000 / precio $200.00 = 25 acciones
        safe_qty_eq = self.risk_engine.calculate_max_safe_quantity(
            price=Decimal("200.00"),
            budget=Decimal("5000.00"),
            asset_class="equity",
        )
        self.assertEqual(safe_qty_eq, 25)

        # Para opciones: presupuesto $5,000 / (precio $2.00 x 100) = 25 contratos
        safe_qty_opt = self.risk_engine.calculate_max_safe_quantity(
            price=Decimal("2.00"),
            budget=Decimal("5000.00"),
            asset_class="option",
        )
        self.assertEqual(safe_qty_opt, 25)

        # Para opciones con precio $200.00 / acción -> $20,000 / contrato -> 0 contratos
        safe_qty_opt_expensive = self.risk_engine.calculate_max_safe_quantity(
            price=Decimal("200.00"),
            budget=Decimal("5000.00"),
            asset_class="option",
        )
        self.assertEqual(safe_qty_opt_expensive, 0)


if __name__ == "__main__":
    unittest.main()

