"""
Tier 4: Real-World Workload Scenarios E2E Test Suite (>=5 Realistic Scenarios).
Simulates complete multi-step autonomous trading workflows.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.account import AccountSnapshot, calculate_trade_limits, check_account_health
from src.data.market import screen_ticker_liquidity
from src.execution.alpaca_executor import ExecutionResult, OptionExecutor
from src.execution.trade_logger import TradeLogEntry, TradeLogger
from src.options.chain_filter import filter_option_chain, find_target_delta_contract
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal
from tests.e2e.fixtures import (
    Draft07SchemaValidator,
    MockAccountSnapshotFactory,
    MockCLIRunnerSimulator,
    MockMCPStdioProtocolSimulator,
    MockOptionContractFactory,
)


class TestTier4RealWorldScenarios(unittest.TestCase):
    """
    Tier 4 E2E Workload Scenarios: Full realistic lifecycle simulations
    validating the complete end-to-end pipeline under real-world market conditions.
    """

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "e2e_scenarios_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)
        self.mcp_sim = MockMCPStdioProtocolSimulator()

    def tearDown(self):
        self.temp_dir.cleanup()

    # =========================================================================
    # Scenario 1: Bullish Momentum Breakout on SPY (Happy Path)
    # =========================================================================

    def test_scenario_01_bullish_momentum_breakout_happy_path(self):
        """
        Scenario 1: Bullish Momentum Breakout (ATM Call Swing).
        Healthy account -> SPY screened -> Trend bullish -> ATM Call selected
        -> RiskEngine 5% approval -> Paper order execution -> Draft-07 audit logged.
        """
        # Step 1: Ingest account state
        account = MockAccountSnapshotFactory.create_healthy_account(
            portfolio_value=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("100000.00"),
        )
        health = check_account_health(account)
        self.assertTrue(health.can_trade)

        # Step 2: Screen underlying ticker liquidity
        score = screen_ticker_liquidity(
            ticker="SPY",
            daily_volume=30000000,
            bid_price=Decimal("500.10"),
            ask_price=Decimal("500.15"),
            option_open_interest=60000,
        )
        self.assertTrue(score.is_tradable)
        self.assertGreaterEqual(score.stars, 4)

        # Step 3: Screen option chain and select optimal ATM Call contract
        c_atm = MockOptionContractFactory.create_valid_contract(
            symbol="SPY260930C00500000",
            strike_price="500.00",
            bid_price="2.10",
            ask_price="2.20",  # $220/contract
            dte=20,
            open_interest=2500,
            delta="0.50",
            theta="-0.04",
        )
        c_otm = MockOptionContractFactory.create_valid_contract(
            symbol="SPY260930C00520000",
            strike_price="520.00",
            bid_price="0.80",
            ask_price="0.85",
            dte=20,
            open_interest=1200,
            delta="0.25",
        )
        filtered_chain = filter_option_chain([c_atm, c_otm])
        selected_contract = find_target_delta_contract(filtered_chain, OptionType.CALL, Decimal("0.50"))
        self.assertIsNotNone(selected_contract)
        self.assertEqual(selected_contract.symbol, "SPY260930C00500000")

        # Step 4: Formulate trade proposal (5 contracts = $1,100 cost)
        proposal = TradeProposal(
            contract=selected_contract,
            quantity=5,
            strategy_name="BullishMomentumBreakout",
            action="BUY",
        )

        # Step 5: Evaluate pre-trade risk guardrail
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("1100.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0110"))

        # Step 6: Dispatch execution and record audit trail
        sim_order_id = "paper-order-scenario-1"
        entry = self.logger.log_executed_trade(
            proposal=proposal,
            verdict=verdict,
            order_id=sim_order_id,
            status="FILLED",
        )
        self.assertEqual(entry.execution_status, "FILLED")

        # Step 7: Verify audit record conforms to Draft-07 schema
        draft07_record = {
            "timestamp": entry.timestamp,
            "event_type": "TRADE_EXECUTED",
            "mode": "scan",
            "market_data_snapshot": {
                "ticker": selected_contract.underlying_symbol,
                "underlying_price": "500.12",
                "option_symbol": selected_contract.symbol,
                "bid_price": str(selected_contract.bid_price),
                "ask_price": str(selected_contract.ask_price),
                "mid_price": str(selected_contract.mid_price),
                "spread_pct": str(selected_contract.bid_ask_spread_pct),
                "volume": selected_contract.volume,
                "open_interest": selected_contract.open_interest,
                "greeks": selected_contract.greeks.to_dict(),
            },
            "agent_proposal": {
                "strategy_name": proposal.strategy_name,
                "signal_type": "BULLISH_CALL_MOMENTUM",
                "confidence": "0.85",
                "target_contract_symbol": selected_contract.symbol,
                "target_option_type": "CALL",
                "action": proposal.action,
                "quantity": proposal.quantity,
            },
            "risk_verdict": {
                "is_approved": verdict.is_approved,
                "trade_cost": str(verdict.trade_cost),
                "max_allowed_budget": str(verdict.max_allowed_budget),
                "portfolio_risk_pct_used": str(verdict.portfolio_risk_pct_used),
                "reasons": verdict.reasons,
                "reason_codes": [],
            },
            "execution_result": {
                "executed": True,
                "order_id": sim_order_id,
                "execution_status": "FILLED",
            },
        }
        is_valid, errors = Draft07SchemaValidator.validate(draft07_record)
        self.assertTrue(is_valid, f"Draft-07 errors: {errors}")

    # =========================================================================
    # Scenario 2: Hallucinated Far-OTM "Lottery Ticket" Interception
    # =========================================================================

    def test_scenario_02_hallucinated_lottery_ticket_interception(self):
        """
        Scenario 2: AI Agent hallucinates high-strike speculative Call.
        Deep OTM, 60 DTE, low OI, wide spread -> RiskEngine intercepts and halts trade
        -> Zero broker order dispatched -> TRADE_REJECTED audit logged.
        """
        account = MockAccountSnapshotFactory.create_healthy_account()

        # Hallucinated contract: DTE = 60 (>30), OI = 80 (<500), Spread = 25% (>5%), Delta = 0.12 (<0.30)
        hallucinated_contract = MockOptionContractFactory.create_valid_contract(
            symbol="SPY261130C00600000",
            strike_price="600.00",
            bid_price="0.30",
            ask_price="0.40",
            dte=60,
            open_interest=80,
            delta="0.12",
        )
        proposal = TradeProposal(
            contract=hallucinated_contract,
            quantity=10,
            strategy_name="HallucinatedSpeculationAgent",
        )

        # Risk Engine evaluates trade
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        # Verify multiple guardrails fired
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("DTE inválido", reasons_text)
        self.assertIn("Open Interest insuficiente", reasons_text)
        self.assertIn("Spread Bid/Ask excesivo", reasons_text)

        # Execution layer strictly blocks submission
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

        # Audit trail records rejection
        history = self.logger.get_trade_history(limit=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")
        self.assertFalse(history[0].is_approved)

    # =========================================================================
    # Scenario 3: Excessive Position Sizing (5% Rule Guardrail)
    # =========================================================================

    def test_scenario_03_excessive_position_sizing_guardrail(self):
        """
        Scenario 3: Excessive Position Sizing.
        Agent proposes $7,500 trade on $100k account (7.5% > 5%) -> Blocked
        -> Safe sizing recommendation calculated -> Preserves capital.
        """
        account = MockAccountSnapshotFactory.create_healthy_account(portfolio_value=Decimal("100000.00"))
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.50")  # $250/contract

        # Agent proposes 30 contracts = $7,500 (7.50% of portfolio)
        proposal = TradeProposal(contract=contract, quantity=30, strategy_name="OverAggressiveAgent")
        verdict = self.risk_engine.evaluate_trade(proposal, account)

        self.assertFalse(verdict.is_approved)
        self.assertIn("excede el límite del 5.000%", verdict.reasons[0])

        # Recommended quantity = $5,000 // $250 = 20 contracts
        self.assertEqual(verdict.recommended_quantity, 20)

        # Execution layer blocks order
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)

    # =========================================================================
    # Scenario 4: High-Volatility Market Opening Spike (Crossed Quote)
    # =========================================================================

    def test_scenario_04_market_opening_volatility_spike_crossed_quote(self):
        """
        Scenario 4: Volatility Opening Spike (Crossed Market).
        Bid $3.50 > Ask $3.20 -> Crossed quote detected -> Infrangible gate halts trade.
        """
        account = MockAccountSnapshotFactory.create_healthy_account()
        crossed_contract = MockOptionContractFactory.create_crossed_quote_contract()
        proposal = TradeProposal(contract=crossed_contract, quantity=2, strategy_name="OpeningVolTrader")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        executor = OptionExecutor(trading_client=None, logger=self.logger)
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

    # =========================================================================
    # Scenario 5: Account Capital Depletion & Margin Stress Scenario
    # =========================================================================

    def test_scenario_05_account_capital_depletion_margin_stress(self):
        """
        Scenario 5: Depleted Cash and Margin Pressure.
        Cash depleted to $400 -> Proposed trade of $1,100 rejected -> Recommended quantity calculated.
        """
        account = MockAccountSnapshotFactory.create_low_cash_account(cash=Decimal("400.00"))
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.20")  # $220/contract

        # Proposes 5 contracts = $1,100 > $400 cash
        proposal = TradeProposal(contract=contract, quantity=5, strategy_name="StressedAccountTrader")
        verdict = self.risk_engine.evaluate_trade(proposal, account)

        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("presupuesto efectivo" in r for r in verdict.reasons))

        # $400 // $220 = 1 safe contract
        self.assertEqual(verdict.recommended_quantity, 1)

        # Audit log written
        entry = self.logger.log_rejected_trade(proposal, verdict)
        self.assertEqual(entry.event_type, "TRADE_REJECTED")
        self.assertFalse(entry.is_approved)


if __name__ == "__main__":
    unittest.main()
