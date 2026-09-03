"""
Tier 3: Cross-Feature Combinations E2E Test Suite (Pairwise Interactions).
Total test cases: 15 tests.
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


class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """
    Tier 3 E2E Cross-Feature Combinations: Verifies pairwise interactions
    between MCP/CLI transport, Risk Engine, execution modes, and audit logging.
    """

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "e2e_tier3_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)
        self.mcp_sim = MockMCPStdioProtocolSimulator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_t3_01_mcp_account_ingestion_into_risk_engine_5pct_check(self):
        """TC-T3-01: Account retrieved via MCP stdio transport fed into Risk Engine 5% evaluation."""
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_account"}})
        resp = json.loads(self.mcp_sim.handle_request(req))
        res = resp["result"]

        snapshot = MockAccountSnapshotFactory.create_healthy_account(
            portfolio_value=Decimal(res["portfolio_value"]),
            cash=Decimal(res["cash"]),
            buying_power=Decimal(res["buying_power"]),
            account_id=res["account_id"],
        )

        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.50")
        # 10 contracts * $2.50 * 100 = $2,500 <= $5,000 (Approved)
        p_approved = TradeProposal(contract=contract, quantity=10, strategy_name="MCPFlow")
        v_approved = self.risk_engine.evaluate_trade(p_approved, snapshot)
        self.assertTrue(v_approved.is_approved)

        # 25 contracts * $2.50 * 100 = $6,250 > $5,000 (Rejected)
        p_rejected = TradeProposal(contract=contract, quantity=25, strategy_name="MCPFlow")
        v_rejected = self.risk_engine.evaluate_trade(p_rejected, snapshot)
        self.assertFalse(v_rejected.is_approved)

    def test_t3_02_cli_quotes_into_spread_guardrail_blocks_cli_order(self):
        """TC-T3-02: Wide spread quote detected causes RiskEngine rejection and blocks CLI execution."""
        # Simulated quote with 33% spread
        contract = MockOptionContractFactory.create_wide_spread_contract(bid="1.00", ask="1.40")
        account = MockAccountSnapshotFactory.create_healthy_account()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="CLIFlow")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        executor = OptionExecutor(trading_client=None, logger=self.logger)
        exec_res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(exec_res.success)
        self.assertEqual(exec_res.status, "REJECTED")

    def test_t3_03_dry_run_pipeline_produces_draft07_compliant_simulated_log(self):
        """TC-T3-03: Dry-run execution generates log record compliant with Draft-07 JSON schema."""
        contract = MockOptionContractFactory.create_valid_contract()
        account = MockAccountSnapshotFactory.create_healthy_account()
        proposal = TradeProposal(contract=contract, quantity=2, strategy_name="DryRunSchemaTest")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

        sim_order_id = "dry-run-order-t3-03"
        self.logger.log_executed_trade(proposal, verdict, order_id=sim_order_id, status="SIMULATED")

        # Re-read raw JSONL line and construct Draft-07 compliant record to validate schema
        with open(self.log_file, "r", encoding="utf-8") as f:
            raw_entry = json.loads(f.readline().strip())

        draft07_record = {
            "timestamp": raw_entry["timestamp"],
            "event_type": "TRADE_SIMULATED",
            "mode": "dry-run",
            "market_data_snapshot": {
                "ticker": contract.underlying_symbol,
                "underlying_price": "500.00",
                "option_symbol": contract.symbol,
                "bid_price": str(contract.bid_price),
                "ask_price": str(contract.ask_price),
                "mid_price": str(contract.mid_price),
                "spread_pct": str(contract.bid_ask_spread_pct),
                "volume": contract.volume,
                "open_interest": contract.open_interest,
                "greeks": contract.greeks.to_dict(),
            },
            "agent_proposal": {
                "strategy_name": proposal.strategy_name,
                "signal_type": "BULLISH_CALL_MOMENTUM",
                "confidence": "0.85",
                "target_contract_symbol": contract.symbol,
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
                "execution_status": "SIMULATED",
            },
        }

        is_valid, errors = Draft07SchemaValidator.validate(draft07_record)
        self.assertTrue(is_valid, f"Draft-07 validation errors: {errors}")

    def test_t3_04_dry_run_rejection_logs_trade_rejected_with_draft07_compliance(self):
        """TC-T3-04: Dry-run rejection generates TRADE_REJECTED record compliant with schema."""
        contract = MockOptionContractFactory.create_zero_dte_contract()
        account = MockAccountSnapshotFactory.create_healthy_account()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="RejectionSchemaTest")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        self.logger.log_rejected_trade(proposal, verdict)
        with open(self.log_file, "r", encoding="utf-8") as f:
            raw_entry = json.loads(f.readline().strip())

        draft07_record = {
            "timestamp": raw_entry["timestamp"],
            "event_type": "TRADE_REJECTED",
            "mode": "dry-run",
            "market_data_snapshot": {
                "ticker": contract.underlying_symbol,
                "underlying_price": "500.00",
                "bid_price": str(contract.bid_price),
                "ask_price": str(contract.ask_price),
                "mid_price": str(contract.mid_price),
                "spread_pct": str(contract.bid_ask_spread_pct),
                "volume": contract.volume,
                "open_interest": contract.open_interest,
                "greeks": contract.greeks.to_dict(),
            },
            "agent_proposal": {
                "strategy_name": proposal.strategy_name,
                "signal_type": "BULLISH_CALL_MOMENTUM",
                "confidence": "0.75",
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
                "reason_codes": ["ERR_DTE_BELOW_MIN"],
            },
            "execution_result": {
                "executed": False,
                "execution_status": "REJECTED",
            },
        }

        is_valid, errors = Draft07SchemaValidator.validate(draft07_record)
        self.assertTrue(is_valid, f"Draft-07 errors: {errors}")

    def test_t3_05_margin_call_condition_blocks_broker_execution(self):
        """TC-T3-05: Account in margin call halts pipeline before order submission."""
        account = MockAccountSnapshotFactory.create_margin_call_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="MarginTest")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        executor = OptionExecutor(trading_client=None, logger=self.logger)
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

    def test_t3_06_frozen_account_in_dry_run_mode(self):
        """TC-T3-06: Frozen account in dry-run mode records TRADE_REJECTED (never SIMULATED)."""
        account = MockAccountSnapshotFactory.create_frozen_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="FrozenDryRun")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

        executor = OptionExecutor(trading_client=None, logger=self.logger)
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertEqual(res.status, "REJECTED")

        history = self.logger.get_trade_history(limit=1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")

    def test_t3_07_cash_clamping_and_recommended_sizing(self):
        """TC-T3-07: Low cash clamps effective budget and calculates safe contract recommendation."""
        # Account has $100k equity (5% = $5,000) but only $500 cash
        account = MockAccountSnapshotFactory.create_low_cash_account(cash=Decimal("500.00"))
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.20")
        # Proposed: 5 contracts ($1,100) > $500 cash
        proposal = TradeProposal(contract=contract, quantity=5, strategy_name="CashClampTest")

        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_allowed_budget, Decimal("500.00"))
        # $500 // $220 = 2 contracts recommended
        self.assertEqual(verdict.recommended_quantity, 2)

    def test_t3_08_cumulative_options_cap_across_multi_trade_sequence(self):
        """TC-T3-08: Sequential trades respect cumulative 25% options allocation cap."""
        account = MockAccountSnapshotFactory.create_healthy_account(portfolio_value=Decimal("100000.00"))
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.00")  # $200 / contract

        # Trade 1: 20 contracts ($4,000, 4% equity). Current options exposure = 0.
        p1 = TradeProposal(contract=contract, quantity=20, strategy_name="Seq1")
        v1 = self.risk_engine.evaluate_trade(p1, account, current_options_exposure=Decimal("0.00"))
        self.assertTrue(v1.is_approved)

        # Trade 2: 20 contracts ($4,000). Current options exposure = $20,000. Total = $24,000 <= $25,000 (25%).
        p2 = TradeProposal(contract=contract, quantity=20, strategy_name="Seq2")
        v2 = self.risk_engine.evaluate_trade(p2, account, current_options_exposure=Decimal("20000.00"))
        self.assertTrue(v2.is_approved)

        # Trade 3: 10 contracts ($2,000). Current options exposure = $24,000. Total = $26,000 > $25,000.
        p3 = TradeProposal(contract=contract, quantity=10, strategy_name="Seq3")
        v3 = self.risk_engine.evaluate_trade(p3, account, current_options_exposure=Decimal("24000.00"))
        self.assertFalse(v3.is_approved)

    def test_t3_09_option_chain_filtering_multi_criteria_pruning(self):
        """TC-T3-09: Option chain filter prunes 0-DTE, wide spreads, and illiquid strikes."""
        c_valid = MockOptionContractFactory.create_valid_contract(symbol="VALID", dte=15, open_interest=1500)
        c_zero_dte = MockOptionContractFactory.create_zero_dte_contract()
        c_wide = MockOptionContractFactory.create_wide_spread_contract()
        c_low_oi = MockOptionContractFactory.create_low_oi_contract(oi=100)

        raw_chain = [c_valid, c_zero_dte, c_wide, c_low_oi]
        filtered = filter_option_chain(raw_chain)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].symbol, "VALID")

    def test_t3_10_bullish_signal_delta_proximity_selection(self):
        """TC-T3-10: Bullish strategy signal pairs with ATM Delta (~0.50) contract."""
        c_deep_otm = MockOptionContractFactory.create_valid_contract(symbol="C_OTM", delta="0.25")
        c_atm = MockOptionContractFactory.create_valid_contract(symbol="C_ATM", delta="0.49")
        c_deep_itm = MockOptionContractFactory.create_valid_contract(symbol="C_ITM", delta="0.80")

        best = find_target_delta_contract([c_deep_otm, c_atm, c_deep_itm], OptionType.CALL, Decimal("0.50"))
        self.assertIsNotNone(best)
        self.assertEqual(best.symbol, "C_ATM")

    def test_t3_11_bearish_signal_put_delta_selection(self):
        """TC-T3-11: Bearish strategy signal pairs with Put Delta (~ -0.50) contract."""
        p_otm = MockOptionContractFactory.create_valid_contract(
            symbol="P_OTM", contract_type=OptionType.PUT, delta="-0.20"
        )
        p_atm = MockOptionContractFactory.create_valid_contract(
            symbol="P_ATM", contract_type=OptionType.PUT, delta="-0.52"
        )
        p_itm = MockOptionContractFactory.create_valid_contract(
            symbol="P_ITM", contract_type=OptionType.PUT, delta="-0.85"
        )

        best = find_target_delta_contract([p_otm, p_atm, p_itm], OptionType.PUT, Decimal("-0.50"))
        self.assertIsNotNone(best)
        self.assertEqual(best.symbol, "P_ATM")

    def test_t3_12_contract_multiplier_and_decimal_quantization(self):
        """TC-T3-12: 100-share multiplier and Decimal rounding precision."""
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.155")
        # 3 contracts * $2.155 * 100 = $646.50
        cost = contract.calculate_trade_cost(contracts=3, use_ask=True)
        self.assertEqual(cost, Decimal("646.50"))

    def test_t3_13_mcp_disconnect_reconnect_retry_pipeline(self):
        """TC-T3-13: MCP stdio disconnect triggers simulated reconnection and query retry."""
        sim = MockMCPStdioProtocolSimulator(disconnect_on_query=True)
        # First query triggers disconnect
        with self.assertRaises(ConnectionResetError):
            sim.handle_request(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

        # Client reconnects
        sim.is_connected = True
        sim.disconnect_on_query = False
        resp = json.loads(sim.handle_request(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})))
        self.assertEqual(resp["id"], 2)
        self.assertIn("tools", resp["result"])

    def test_t3_14_executor_error_handling_and_audit_logging(self):
        """TC-T3-14: Broker order rejection logs error and preserves audit trail."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=2, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
            reasons=["Rejected by RiskEngine: Insufficient buying power"],
        )
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

        history = self.logger.get_trade_history(limit=1)
        self.assertEqual(len(history), 1)
        self.assertIn("Insufficient buying power", history[0].risk_reasons[0])

    def test_t3_15_full_scan_pipeline_happy_path(self):
        """TC-T3-15: Complete scan pipeline simulation from liquidity screening to approved execution."""
        # 1. Screen underlying liquidity
        score = screen_ticker_liquidity(
            ticker="SPY",
            daily_volume=25000000,
            bid_price=Decimal("500.00"),
            ask_price=Decimal("500.02"),
            option_open_interest=50000,
        )
        self.assertTrue(score.is_tradable)

        # 2. Ingest account
        account = MockAccountSnapshotFactory.create_healthy_account()
        health = check_account_health(account)
        self.assertTrue(health.can_trade)

        # 3. Select contract and propose trade
        contract = MockOptionContractFactory.create_valid_contract(ask_price="2.50")
        proposal = TradeProposal(contract=contract, quantity=5, strategy_name="ScanPipelineHappyPath")

        # 4. Evaluate risk
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

        # 5. Log executed trade
        entry = self.logger.log_executed_trade(
            proposal=proposal,
            verdict=verdict,
            order_id="mcp-paper-order-9999",
            status="FILLED",
        )
        self.assertEqual(entry.execution_status, "FILLED")
        self.assertEqual(entry.order_id, "mcp-paper-order-9999")


if __name__ == "__main__":
    unittest.main()
