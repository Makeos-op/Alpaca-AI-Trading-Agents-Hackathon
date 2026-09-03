"""
Adversarial Stress Test Harness for Deterministic RiskEngine & Infrangible OptionExecutor.

Adversarially challenges and verifies:
1. Trade cost at 4.9999% (pass) vs 5.0001% (reject) & exact 5.0000% boundary.
2. Buying power exhaustion and cash deficit handling.
3. Cumulative options allocation cap (25.0000% pass vs 25.0001% reject).
4. Crossed and zero quotes (bid >= ask, bid <= 0, ask <= 0).
5. Wide spreads (>5.00% or >$0.50, and underlying spread > 1.00%).
6. Illiquid contracts (volume < 100, OI < 500).
7. 0-DTE pin risk contracts (DTE < 1) and far DTE (> 30).
8. Delta boundary violations (Call delta 0.29, 0.71; Put delta -0.29, -0.71).
9. Theta decay velocity violations (|theta|/ask > 0.05 or |theta| > 0.15).
10. Infrangible broker blocking: OptionExecutor NEVER calls broker when verdict is rejected.
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from src.account import AccountSnapshot
from src.execution.alpaca_executor import (
    ExecutionResult,
    OptionExecutor,
    mcp_evaluate_and_execute_option_trade,
)
from src.execution.trade_logger import TradeLogger
from src.options.models import OptionContract, OptionType
from src.risk.models import (
    RiskConfig,
    RiskReasonCode,
    RiskVerdict,
    TradeProposal,
)
from src.risk.risk_engine import RiskEngine


class MockHostileBrokerGateway:
    """
    Adversarial mock broker gateway.
    Raises AssertionError if any order execution method is invoked.
    Used to mathematically prove the infrangibility of the RiskEngine guardrail.
    """

    def __init__(self, account_snapshot: Optional[AccountSnapshot] = None):
        self.account_snapshot = account_snapshot
        self.call_count = 0

    def get_account(self) -> AccountSnapshot:
        if self.account_snapshot is None:
            return AccountSnapshot(
                account_id="acc-hostile-test",
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
        return self.account_snapshot

    def submit_option_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        raise AssertionError(
            f"CRITICAL BREACH: MockHostileBrokerGateway.submit_option_order was called "
            f"with args={args}, kwargs={kwargs}! Infrangible blocking gate failed."
        )

    def submit_order(self, *args: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        raise AssertionError(
            f"CRITICAL BREACH: MockHostileBrokerGateway.submit_order was called "
            f"with args={args}, kwargs={kwargs}! Infrangible blocking gate failed."
        )


class BaseAdversarialRiskTestCase(unittest.TestCase):
    """Shared base setup with standard test contracts and accounts."""

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "adversarial_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)

        # Baseline healthy account with $100,000 equity, $50,000 cash, $100,000 buying power
        self.healthy_snapshot = AccountSnapshot(
            account_id="acc-adv-healthy",
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

        # Baseline compliant call option contract
        self.valid_call = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=1500,
            open_interest=3000,
            delta="0.45",
            gamma="0.05",
            theta="-0.04",
            vega="0.10",
            implied_volatility="0.20",
        )

        # Baseline compliant put option contract
        self.valid_put = OptionContract.create(
            symbol="SPY260930P00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=1500,
            open_interest=3000,
            delta="-0.45",
            gamma="0.05",
            theta="-0.04",
            vega="0.10",
            implied_volatility="0.20",
        )

    def tearDown(self):
        self.temp_dir.cleanup()


# =============================================================================
# 1. Trade Cost 5% Boundary Stress Testing
# =============================================================================

class TestAdversarialTradeCostLimits(BaseAdversarialRiskTestCase):
    """
    Stress-tests the 5% portfolio risk boundary with precision down to 0.0001%.
    Boundary: Exactly $5,000.00 on $100,000 equity.
    """

    def test_trade_cost_at_4_9999_percent_must_pass(self):
        """Cost = $4,999.90 (4.9999% of $100,000 portfolio) must be APPROVED."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.90",
            ask_price="4.9999",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="BoundaryTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)
        self.assertEqual(verdict.trade_cost, Decimal("4999.90"))
        self.assertLessEqual(verdict.trade_cost, Decimal("5000.00"))

    def test_trade_cost_at_exact_5_0000_percent_must_pass(self):
        """Cost = $5,000.00 (exact 5.0000% border of $100,000 portfolio) must be APPROVED."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.90",
            ask_price="5.0000",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="BoundaryTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.APPROVED)
        self.assertEqual(verdict.trade_cost, Decimal("5000.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0500"))

    def test_trade_cost_at_5_0001_percent_must_reject(self):
        """Cost = $5,000.10 (5.0001% of $100,000 portfolio) must be REJECTED."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.95",
            ask_price="5.0001",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="BoundaryTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)
        self.assertIn(RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT, verdict.reason_codes)
        self.assertEqual(verdict.trade_cost, Decimal("5000.10"))
        self.assertGreater(verdict.trade_cost, Decimal("5000.00"))

    def test_trade_cost_one_cent_over_5_percent_must_reject(self):
        """Cost = $5,000.01 (one cent overrun) must be REJECTED."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="49.80",
            ask_price="50.0001",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        # 1 contract * $50.0001 * 100 = $5,000.01
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="BoundaryTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)
        self.assertEqual(verdict.trade_cost, Decimal("5000.01"))

    def test_scale_invariance_small_account(self):
        """Small $10,000 account: 5% limit is $500.00. Test $499.99 pass vs $500.01 reject."""
        small_snapshot = AccountSnapshot(
            account_id="acc-small",
            cash=Decimal("10000.00"),
            portfolio_value=Decimal("10000.00"),
            buying_power=Decimal("10000.00"),
            equity=Decimal("10000.00"),
            long_market_value=Decimal("0.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("10000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        # 4.9999% of $10,000 = $499.99 -> PASS
        c_pass = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.90",
            ask_price="4.9999",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        v_pass = self.risk_engine.evaluate_trade(
            TradeProposal(contract=c_pass, quantity=1, strategy_name="SmallAcc"),
            small_snapshot,
        )
        self.assertTrue(v_pass.is_approved)

        # 5.0001% of $10,000 = $500.01 -> REJECT
        c_fail = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.95",
            ask_price="5.0001",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        v_fail = self.risk_engine.evaluate_trade(
            TradeProposal(contract=c_fail, quantity=1, strategy_name="SmallAcc"),
            small_snapshot,
        )
        self.assertFalse(v_fail.is_approved)
        self.assertEqual(v_fail.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)

    def test_limit_price_override_exceeds_5_percent(self):
        """When limit_price > ask_price, effective trade cost must use limit price and reject if > 5%."""
        # Ask is $4.00 ($400/contract), but agent specified limit_price = $5.05 ($505/contract)
        # 10 contracts @ $5.05 = $5,050.00 > $5,000.00 (5% of $100k)
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="3.90",
            ask_price="4.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(
            contract=contract,
            quantity=10,
            strategy_name="LimitOverride",
            limit_price=Decimal("5.05"),
        )
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.reason_code, RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT)
        self.assertEqual(verdict.trade_cost, Decimal("5050.00"))


# =============================================================================
# 2. Buying Power Exhaustion and Cash Deficits
# =============================================================================

class TestAdversarialBuyingPowerAndCashDeficits(BaseAdversarialRiskTestCase):
    """
    Stress-tests buying power exhaustion, cash deficits, margin calls, and account restrictions.
    """

    def test_cash_deficit_below_trade_cost(self):
        """Trade cost ($2,250) is < 5% ($5,000) and < BP ($100k), but exceeds cash ($1,500). Must REJECT."""
        cash_depleted_snap = AccountSnapshot(
            account_id="acc-low-cash",
            cash=Decimal("1500.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("98500.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("100000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        # 10 contracts * $2.25 * 100 = $2,250.00 > $1,500.00 cash
        proposal = TradeProposal(contract=self.valid_call, quantity=10, strategy_name="CashDeficit")
        verdict = self.risk_engine.evaluate_trade(proposal, cash_depleted_snap)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_CASH, verdict.reason_codes)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER, verdict.reason_codes)
        # Max safe contracts: floor($1500 / $225) = 6 contracts
        self.assertEqual(verdict.max_safe_quantity, 6)

    def test_buying_power_exhaustion(self):
        """Trade cost ($2,250) is < 5% and < cash, but exceeds buying power ($1,200). Must REJECT."""
        bp_depleted_snap = AccountSnapshot(
            account_id="acc-low-bp",
            cash=Decimal("50000.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("1200.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("50000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("48800.00"),
            maintenance_margin=Decimal("30000.00"),
            daytrading_buying_power=Decimal("1200.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        proposal = TradeProposal(contract=self.valid_call, quantity=10, strategy_name="BPExhaustion")
        verdict = self.risk_engine.evaluate_trade(proposal, bp_depleted_snap)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_BUYING_POWER, verdict.reason_codes)
        # Max safe contracts: floor($1200 / $225) = 5 contracts
        self.assertEqual(verdict.max_safe_quantity, 5)

    def test_zero_cash_and_zero_buying_power(self):
        """Zero cash or zero buying power must reject with max_safe_quantity = 0."""
        zero_snap = AccountSnapshot(
            account_id="acc-zero",
            cash=Decimal("0.00"),
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("0.00"),
            equity=Decimal("100000.00"),
            long_market_value=Decimal("100000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        proposal = TradeProposal(contract=self.valid_call, quantity=1, strategy_name="ZeroCap")
        verdict = self.risk_engine.evaluate_trade(proposal, zero_snap)

        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_safe_quantity, 0)
        self.assertEqual(verdict.max_allowed_budget, Decimal("0.00"))

    def test_margin_call_risk_equity_equals_maintenance(self):
        """Maintenance margin >= equity triggers critical margin call rejection."""
        margin_call_snap = AccountSnapshot(
            account_id="acc-margin-call",
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("50000.00"),
            buying_power=Decimal("50000.00"),
            equity=Decimal("50000.00"),
            long_market_value=Decimal("45000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("40000.00"),
            maintenance_margin=Decimal("50000.00"),  # Exactly equal to equity!
            daytrading_buying_power=Decimal("50000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        proposal = TradeProposal(contract=self.valid_call, quantity=1, strategy_name="MarginTest")
        verdict = self.risk_engine.evaluate_trade(proposal, margin_call_snap)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED, verdict.reason_codes)

    def test_frozen_and_inactive_accounts(self):
        """Frozen or inactive accounts must reject with ERR_ACCOUNT_FROZEN_OR_RESTRICTED."""
        frozen_snap = AccountSnapshot(
            account_id="acc-frozen",
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
            is_frozen=True,
        )
        proposal = TradeProposal(contract=self.valid_call, quantity=1, strategy_name="FrozenTest")
        verdict = self.risk_engine.evaluate_trade(proposal, frozen_snap)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_ACCOUNT_FROZEN_OR_RESTRICTED, verdict.reason_codes)


# =============================================================================
# 3. Cumulative Options Allocation Cap (25%)
# =============================================================================

class TestAdversarialCumulativeOptionsAllocation(BaseAdversarialRiskTestCase):
    """
    Stress-tests the 25.0000% cumulative portfolio options allocation cap.
    """

    def test_cumulative_cap_exact_25_0000_percent_passes(self):
        """Current ($20,000.00) + New Trade ($5,000.00) = $25,000.00 (exact 25%) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.90",
            ask_price="5.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="CapTest")
        verdict = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            current_options_exposure=Decimal("20000.00"),
        )
        self.assertTrue(verdict.is_approved)

    def test_cumulative_cap_at_25_0001_percent_rejects(self):
        """Current ($20,000.10) + New Trade ($5,000.00) = $25,000.10 (> 25%) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="4.90",
            ask_price="5.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="CapTest")
        verdict = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            current_options_exposure=Decimal("20000.10"),
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP, verdict.reason_codes)

    def test_cumulative_cap_already_reached(self):
        """Current exposure already at $25,000.00. Any trade must be REJECTED with max_safe_quantity = 0."""
        proposal = TradeProposal(contract=self.valid_call, quantity=1, strategy_name="AtCap")
        verdict = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            current_options_exposure=Decimal("25000.00"),
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP, verdict.reason_codes)
        self.assertEqual(verdict.max_safe_quantity, 0)

    def test_safe_quantity_clamped_by_remaining_options_cap(self):
        """
        Current exposure $24,400.00 on $100k portfolio. Remaining cap = $600.00.
        Contract ask $2.00 ($200/contract). Proposed 5 contracts ($1,000).
        Must REJECT proposed quantity, but compute max_safe_quantity = floor($600/$200) = 3 contracts.
        """
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.95",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.05",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=5, strategy_name="PartialClamp")
        verdict = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            current_options_exposure=Decimal("24400.00"),
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_safe_quantity, 3)


# =============================================================================
# 4. Crossed and Zero Quotes
# =============================================================================

class TestAdversarialQuotationSanity(BaseAdversarialRiskTestCase):
    """
    Stress-tests quote validity: locked markets (bid == ask), crossed quotes (bid > ask),
    and non-positive quotes (bid <= 0 or ask <= 0).
    """

    def test_locked_market_bid_equals_ask_must_reject(self):
        """Bid == Ask ($2.00 / $2.00) is a locked/abnormal market quote. Must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.00",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="LockedQuote")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE, verdict.reason_codes)

    def test_crossed_market_bid_greater_than_ask_must_reject(self):
        """Bid ($2.10) > Ask ($2.00) is a crossed market. Must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.10",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="CrossedQuote")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE, verdict.reason_codes)

    def test_zero_and_negative_bid_quotes_must_reject(self):
        """Zero bid ($0.00) or negative bid (-$0.50) must REJECT."""
        for bad_bid in ("0.00", "-0.50"):
            with self.subTest(bad_bid=bad_bid):
                contract = OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price=bad_bid,
                    ask_price="1.50",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                )
                verdict = self.risk_engine.evaluate_trade(
                    TradeProposal(contract=contract, quantity=1, strategy_name="BadBid"),
                    self.healthy_snapshot,
                )
                self.assertFalse(verdict.is_approved)
                self.assertIn(RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE, verdict.reason_codes)

    def test_zero_and_negative_ask_quotes_must_reject(self):
        """Zero ask ($0.00) or negative ask (-$1.00) must REJECT."""
        for bad_ask in ("0.00", "-1.00"):
            with self.subTest(bad_ask=bad_ask):
                contract = OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="0.50",
                    ask_price=bad_ask,
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                )
                verdict = self.risk_engine.evaluate_trade(
                    TradeProposal(contract=contract, quantity=1, strategy_name="BadAsk"),
                    self.healthy_snapshot,
                )
                self.assertFalse(verdict.is_approved)
                self.assertIn(RiskReasonCode.ERR_CROSSED_OR_ZERO_QUOTE, verdict.reason_codes)


# =============================================================================
# 5. Wide Spreads (>5% or >$0.50)
# =============================================================================

class TestAdversarialSpreadLimits(BaseAdversarialRiskTestCase):
    """
    Stress-tests relative spread (<= 5.00%), absolute spread (<= $0.50), and underlying spread (<= 1.00%).
    """

    def test_relative_spread_exact_5_0000_percent_passes(self):
        """Mid = $2.00, Bid = $1.95, Ask = $2.05 -> Spread = 0.10 / 2.00 = 5.0000% must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.95",
            ask_price="2.05",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="SpreadTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)

    def test_relative_spread_5_01_percent_fails(self):
        """Mid = $2.00, Bid = $1.94, Ask = $2.06 -> Spread = 0.12 / 2.00 = 6.00% > 5.00% must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.94",
            ask_price="2.06",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="SpreadTest")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, verdict.reason_codes)

    def test_absolute_spread_exact_50_cents_passes(self):
        """Ask ($20.30) - Bid ($19.80) = $0.50 (exact absolute limit) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="19.80",
            ask_price="20.30",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        # Relative spread: 0.50 / 20.05 = 2.49% <= 5%, absolute spread = $0.50 <= $0.50
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="AbsSpreadPass")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
        self.assertTrue(verdict.is_approved)

    def test_absolute_spread_51_cents_fails(self):
        """Ask ($20.30) - Bid ($19.79) = $0.51 > $0.50 must REJECT even if relative spread is < 5%."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="19.79",
            ask_price="20.30",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        # Relative spread is 2.54% <= 5%, but absolute spread is $0.51 > $0.50
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="AbsSpreadFail")
        verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)

        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, verdict.reason_codes)

    def test_underlying_spread_violations(self):
        """Underlying spread > 1.00% must REJECT."""
        proposal = TradeProposal(contract=self.valid_call, quantity=1, strategy_name="UnderlyingSpread")

        # Explicit kwarg underlying_spread_pct = 1.01%
        v1 = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            underlying_spread_pct=Decimal("0.0101"),
        )
        self.assertFalse(v1.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, v1.reason_codes)

        # Underlying quotes: bid $500, ask $506 -> spread = 6/503 = 1.19% > 1.00%
        v2 = self.risk_engine.evaluate_trade(
            proposal,
            self.healthy_snapshot,
            underlying_bid=Decimal("500.00"),
            underlying_ask=Decimal("506.00"),
        )
        self.assertFalse(v2.is_approved)
        self.assertIn(RiskReasonCode.ERR_WIDE_BID_ASK_SPREAD, v2.reason_codes)


# =============================================================================
# 6. Illiquid Contracts (Volume < 100, OI < 500)
# =============================================================================

class TestAdversarialLiquidityFloors(BaseAdversarialRiskTestCase):
    """
    Stress-tests contract liquidity floors: Open Interest >= 500 and daily Volume >= 100.
    """

    def test_open_interest_exact_500_passes(self):
        """OI = 500 (exact threshold) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=500,
            open_interest=500,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="OIBoundary"),
            self.healthy_snapshot,
        )
        self.assertTrue(verdict.is_approved)

    def test_open_interest_499_fails(self):
        """OI = 499 (one below threshold) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=500,
            open_interest=499,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="OIBreak"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_OPEN_INTEREST, verdict.reason_codes)

    def test_volume_exact_100_passes(self):
        """Volume = 100 (exact threshold) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=100,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="VolBoundary"),
            self.healthy_snapshot,
        )
        self.assertTrue(verdict.is_approved)

    def test_volume_99_fails(self):
        """Volume = 99 (one below threshold) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=99,
            open_interest=1000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="VolBreak"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_VOLUME, verdict.reason_codes)

    def test_compound_illiquidity_captures_both_reasons(self):
        """Volume = 50 and OI = 200 must capture both error reason codes."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.15",
            ask_price="2.25",
            volume=50,
            open_interest=200,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="CompoundIlliquid"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_OPEN_INTEREST, verdict.reason_codes)
        self.assertIn(RiskReasonCode.ERR_INSUFFICIENT_VOLUME, verdict.reason_codes)


# =============================================================================
# 7. 0-DTE Pin Risk and DTE Horizons (1 to 30)
# =============================================================================

class TestAdversarialDTEHorizons(BaseAdversarialRiskTestCase):
    """
    Stress-tests DTE horizons: 0-DTE pin risk, expired contracts, and far-out DTE > 30.
    """

    def test_zero_dte_pin_risk_must_reject(self):
        """DTE = 0 (same day expiration pin risk) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=0,
            bid_price="2.15",
            ask_price="2.25",
            volume=2000,
            open_interest=3000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="ZeroDTE"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS, verdict.reason_codes)

    def test_negative_dte_expired_contract_must_reject(self):
        """DTE = -1 (expired contract) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=-1,
            bid_price="2.15",
            ask_price="2.25",
            volume=2000,
            open_interest=3000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="Expired"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS, verdict.reason_codes)

    def test_dte_exact_lower_bound_1_passes(self):
        """DTE = 1 (1 day to expiry) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=1,
            bid_price="2.15",
            ask_price="2.25",
            volume=2000,
            open_interest=3000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="DTE1"),
            self.healthy_snapshot,
        )
        self.assertTrue(verdict.is_approved)

    def test_dte_exact_upper_bound_30_passes(self):
        """DTE = 30 (exact upper swing window) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=30,
            bid_price="2.15",
            ask_price="2.25",
            volume=2000,
            open_interest=3000,
            delta="0.50",
            theta="-0.04",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="DTE30"),
            self.healthy_snapshot,
        )
        self.assertTrue(verdict.is_approved)

    def test_dte_31_and_far_out_leaps_must_reject(self):
        """DTE = 31 and DTE = 180 (far-out LEAPS) must REJECT."""
        for bad_dte in (31, 180):
            with self.subTest(bad_dte=bad_dte):
                contract = OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=bad_dte,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=2000,
                    open_interest=3000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                )
                verdict = self.risk_engine.evaluate_trade(
                    TradeProposal(contract=contract, quantity=1, strategy_name="FarDTE"),
                    self.healthy_snapshot,
                )
                self.assertFalse(verdict.is_approved)
                self.assertIn(RiskReasonCode.ERR_DTE_OUT_OF_BOUNDS, verdict.reason_codes)


# =============================================================================
# 8. Delta Boundary Violations (Calls & Puts)
# =============================================================================

class TestAdversarialDeltaBoundaries(BaseAdversarialRiskTestCase):
    """
    Stress-tests Call Delta [0.30, 0.70] and Put Delta [-0.70, -0.30].
    """

    def test_call_delta_boundaries(self):
        """Call Delta: 0.29 (REJECT), 0.30 (PASS), 0.70 (PASS), 0.71 (REJECT)."""
        scenarios = [
            ("0.29", False, "OTM lottery ticket violation"),
            ("0.30", True, "Exact lower delta boundary"),
            ("0.50", True, "ATM standard delta"),
            ("0.70", True, "Exact upper delta boundary"),
            ("0.71", False, "Deep ITM delta violation"),
            ("0.05", False, "Penny lottery ticket OTM call"),
            ("0.98", False, "Deep ITM call"),
        ]
        for delta_str, should_pass, desc in scenarios:
            with self.subTest(delta=delta_str, desc=desc):
                contract = OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta=delta_str,
                    theta="-0.04",
                    implied_volatility="0.20",
                )
                verdict = self.risk_engine.evaluate_trade(
                    TradeProposal(contract=contract, quantity=1, strategy_name="CallDelta"),
                    self.healthy_snapshot,
                )
                self.assertEqual(verdict.is_approved, should_pass)
                if not should_pass:
                    self.assertIn(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS, verdict.reason_codes)

    def test_put_delta_boundaries(self):
        """Put Delta: -0.29 (REJECT), -0.30 (PASS), -0.70 (PASS), -0.71 (REJECT)."""
        scenarios = [
            ("-0.29", False, "OTM lottery ticket put (closer to zero than -0.30)"),
            ("-0.30", True, "Exact upper numerical / least-negative put boundary"),
            ("-0.50", True, "ATM standard put"),
            ("-0.70", True, "Exact lower numerical / most-negative put boundary"),
            ("-0.71", False, "Deep ITM put violation"),
            ("-0.05", False, "Penny lottery ticket OTM put"),
            ("-0.98", False, "Deep ITM put"),
        ]
        for delta_str, should_pass, desc in scenarios:
            with self.subTest(delta=delta_str, desc=desc):
                contract = OptionContract.create(
                    symbol="SPY260930P00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.PUT,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta=delta_str,
                    theta="-0.04",
                    implied_volatility="0.20",
                )
                verdict = self.risk_engine.evaluate_trade(
                    TradeProposal(contract=contract, quantity=1, strategy_name="PutDelta"),
                    self.healthy_snapshot,
                )
                self.assertEqual(verdict.is_approved, should_pass)
                if not should_pass:
                    self.assertIn(RiskReasonCode.ERR_DELTA_OUT_OF_BOUNDS, verdict.reason_codes)


# =============================================================================
# 9. Theta Decay Velocity Violations (|theta|/ask > 0.05)
# =============================================================================

class TestAdversarialThetaDecayVelocity(BaseAdversarialRiskTestCase):
    """
    Stress-tests Theta daily decay velocity (|theta| / ask <= 0.05) and absolute cap (|theta| <= 0.15).
    """

    def test_theta_decay_at_exact_5_0000_percent_passes(self):
        """Ask = $2.00, Theta = -0.10: |theta| / ask = 0.10 / 2.00 = 0.0500 (5.0000%) must PASS."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.95",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.10",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="ThetaBoundary"),
            self.healthy_snapshot,
        )
        self.assertTrue(verdict.is_approved)

    def test_theta_decay_over_5_0000_percent_fails(self):
        """Ask = $2.00, Theta = -0.11: |theta| / ask = 0.11 / 2.00 = 0.0550 (5.50%) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.95",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.11",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="ThetaBreak"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE, verdict.reason_codes)

    def test_theta_decay_subtle_violation_fails(self):
        """Ask = $2.00, Theta = -0.1001: rate = 0.05005 (> 0.0500) must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.95",
            ask_price="2.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.1001",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="ThetaSubtle"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE, verdict.reason_codes)

    def test_theta_absolute_cap_exceeded(self):
        """Ask = $10.00, Theta = -0.16: decay rate is 1.6% (<= 5%), but |theta| = 0.16 > 0.15 cap. Must REJECT."""
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="9.80",
            ask_price="10.00",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.16",
            implied_volatility="0.20",
        )
        verdict = self.risk_engine.evaluate_trade(
            TradeProposal(contract=contract, quantity=1, strategy_name="ThetaAbsCap"),
            self.healthy_snapshot,
        )
        self.assertFalse(verdict.is_approved)
        self.assertIn(RiskReasonCode.ERR_THETA_DECAY_EXCESSIVE, verdict.reason_codes)


# =============================================================================
# 10. Infrangible Broker Blocking: OptionExecutor Never Calls Broker
# =============================================================================

class TestAdversarialInfrangibleBrokerBlocking(BaseAdversarialRiskTestCase):
    """
    Stress-tests the infrangibility of OptionExecutor:
    Verifies that under NO circumstances does OptionExecutor ever invoke broker methods
    when the RiskEngine verdict is not approved (is_approved=False).
    Uses MockHostileBrokerGateway which blows up with AssertionError if invoked.
    """

    def test_hostile_broker_never_called_across_all_failure_modes(self):
        """
        Runs proposals across 10 distinct violation scenarios against OptionExecutor
        wired to MockHostileBrokerGateway. Proves 0 broker calls occur.
        """
        hostile_gw = MockHostileBrokerGateway(self.healthy_snapshot)
        executor = OptionExecutor(gateway=hostile_gw, logger=self.logger, dry_run=False)

        # 10 distinct adversarial rejection scenarios:
        scenarios = [
            # 1. 5% rule overrun ($6,250 > $5,000)
            TradeProposal(
                contract=self.valid_call,
                quantity=28,  # 28 * $2.25 * 100 = $6,300
                strategy_name="5pctOverrun",
            ),
            # 2. 0-DTE pin risk
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=0,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="ZeroDTE",
            ),
            # 3. Crossed quote (bid > ask)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.30",
                    ask_price="2.20",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="CrossedQuote",
            ),
            # 4. Wide spread (10%)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="1.80",
                    ask_price="2.20",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="WideSpread",
            ),
            # 5. Low volume (10 contracts)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=10,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="LowVol",
            ),
            # 6. Low OI (50 contracts)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=50,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="LowOI",
            ),
            # 7. Call Delta out of bounds (0.15)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta="0.15",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="BadDelta",
            ),
            # 8. Excessive Theta decay (8% per day)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="1.95",
                    ask_price="2.00",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.16",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="BadTheta",
            ),
            # 9. Far-out DTE (45 days)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930C00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.CALL,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=45,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta="0.50",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="FarDTE",
            ),
            # 10. Put Delta out of bounds (-0.15)
            TradeProposal(
                contract=OptionContract.create(
                    symbol="SPY260930P00500000",
                    underlying_symbol="SPY",
                    contract_type=OptionType.PUT,
                    strike_price="500.00",
                    expiration_date="2026-09-30",
                    dte=15,
                    bid_price="2.15",
                    ask_price="2.25",
                    volume=1000,
                    open_interest=2000,
                    delta="-0.15",
                    theta="-0.04",
                    implied_volatility="0.20",
                ),
                quantity=1,
                strategy_name="BadPutDelta",
            ),
        ]

        for i, proposal in enumerate(scenarios, 1):
            with self.subTest(scenario=proposal.strategy_name):
                verdict = self.risk_engine.evaluate_trade(proposal, self.healthy_snapshot)
                self.assertFalse(verdict.is_approved, f"Scenario {proposal.strategy_name} was unexpectedly approved!")

                # Execute through executor wired to hostile broker
                result = executor.execute_approved_trade(proposal, verdict, dry_run=False)

                # Assertions confirming complete protection:
                self.assertFalse(result.success)
                self.assertEqual(result.status, "REJECTED")
                self.assertIsNone(result.order_id)
                self.assertIn("Orden cancelada por el Risk Engine", result.error_message)

        # Confirm ZERO calls reached the hostile broker
        self.assertEqual(hostile_gw.call_count, 0)

    def test_mcp_evaluate_and_execute_option_trade_prevents_broker_mutation(self):
        """
        Tests the unified MCP tool wrapper `mcp_evaluate_and_execute_option_trade`.
        Verifies that passing hazardous trade inputs produces a rejected verdict,
        rejected execution, and ZERO broker mutation.
        """
        hostile_gw = MockHostileBrokerGateway(self.healthy_snapshot)

        # Invalid contract: DTE = 0 (pin risk) and spread > 5%
        contract_dict = {
            "symbol": "SPY260930C00500000",
            "underlying_symbol": "SPY",
            "contract_type": "CALL",
            "strike_price": "500.00",
            "expiration_date": "2026-09-30",
            "dte": 0,
            "bid_price": "1.80",
            "ask_price": "2.20",
            "volume": 2000,
            "open_interest": 3000,
            "delta": "0.50",
            "gamma": "0.05",
            "theta": "-0.04",
            "vega": "0.10",
            "implied_volatility": "0.20",
        }

        output = mcp_evaluate_and_execute_option_trade(
            contract_data=contract_dict,
            quantity=1,
            strategy_name="MCPHostileTest",
            snapshot=self.healthy_snapshot,
            risk_engine=self.risk_engine,
            gateway=hostile_gw,
            dry_run=False,
        )

        self.assertFalse(output["verdict"]["is_approved"])
        self.assertEqual(output["execution"]["status"], "REJECTED")
        self.assertFalse(output["execution"]["success"])
        self.assertEqual(hostile_gw.call_count, 0)


if __name__ == "__main__":
    unittest.main()
