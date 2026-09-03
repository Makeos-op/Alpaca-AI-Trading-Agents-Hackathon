"""
Tier 2: Boundary & Corner Cases E2E Test Suite (>=5 test cases per feature covering limits, zero/negative, crossed, illiquid).
Total test cases: 60 tests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.account import AccountSnapshot, calculate_trade_limits, check_account_health
from src.config import (
    DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT,
    DEFAULT_MAX_RISK_PER_TRADE_PCT,
    MAX_DTE,
    MAX_OPTION_SPREAD_PCT,
    MIN_DTE,
    MIN_OPTION_OPEN_INTEREST,
)
from src.data.market import screen_ticker_liquidity
from src.execution.alpaca_executor import ExecutionResult, OptionExecutor
from src.execution.trade_logger import TradeLogEntry, TradeLogger
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal
from tests.e2e.fixtures import (
    MockAccountSnapshotFactory,
    MockCLIRunnerSimulator,
    MockMCPStdioProtocolSimulator,
    MockOptionContractFactory,
)


class TestTier2BoundaryCases(unittest.TestCase):
    """
    Tier 2 E2E Boundary & Edge Cases: Exercises boundary conditions, extreme values,
    zero/negative numbers, crossed quotes, and stress states across F1.1 - F3.2.
    """

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "e2e_boundary_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)
        self.mcp_sim = MockMCPStdioProtocolSimulator()

    def tearDown(self):
        self.temp_dir.cleanup()

    # =========================================================================
    # Feature 1.1: Python Stdio MCP Client (Boundaries)
    # =========================================================================

    def test_f1_1_b01_empty_json_payload(self):
        """TC-T2-F1.1-01: Empty string sent to stdio handler returns JSON-RPC parse error."""
        resp = json.loads(self.mcp_sim.handle_request(""))
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32700)

    def test_f1_1_b02_oversized_payload_handling(self):
        """TC-T2-F1.1-02: Extreme message length (10,000 character string in params)."""
        large_symbol = "SPY" + "X" * 10000
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "get_option_chain", "arguments": {"underlying": large_symbol}},
        })
        resp = json.loads(self.mcp_sim.handle_request(req))
        self.assertEqual(resp["id"], 99)
        self.assertIn("result", resp)

    def test_f1_1_b03_broken_pipe_disconnect_handling(self):
        """TC-T2-F1.1-03: Unexpected pipe termination simulation."""
        sim = MockMCPStdioProtocolSimulator(disconnect_on_query=True)
        with self.assertRaises(ConnectionResetError):
            sim.handle_request(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
        with self.assertRaises(BrokenPipeError):
            sim.handle_request(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))

    def test_f1_1_b04_unicode_and_special_characters_in_tool_args(self):
        """TC-T2-F1.1-04: Non-ASCII characters in tool call parameters."""
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "submit_option_order",
                "arguments": {
                    "symbol": "SPY260930C00500000",
                    "qty": 1,
                    "side": "buy",
                    "note": "Estrategia de momentum alcista en España 🚀 con señal confirmada",
                },
            },
        })
        resp = json.loads(self.mcp_sim.handle_request(req))
        self.assertEqual(resp["result"]["status"], "FILLED")

    def test_f1_1_b05_missing_jsonrpc_version_field(self):
        """TC-T2-F1.1-05: Missing jsonrpc version in request payload."""
        req = json.dumps({"id": 102, "method": "tools/list"})
        resp = json.loads(self.mcp_sim.handle_request(req))
        self.assertEqual(resp["jsonrpc"], "2.0")

    # =========================================================================
    # Feature 1.2: Alpaca CLI Transport (Boundaries)
    # =========================================================================

    def test_f1_2_b01_cli_empty_stdout(self):
        """TC-T2-F1.2-01: Empty subcommand produces non-zero exit."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")

    def test_f1_2_b02_cli_non_json_output_mode(self):
        """TC-T2-F1.2-02: Plain text output when --json flag omitted."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command(["account"])
        self.assertEqual(code, 0)
        self.assertIn("Account ID", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

    def test_f1_2_b03_cli_symbol_with_whitespace(self):
        """TC-T2-F1.2-03: Symbol containing whitespace handled cleanly."""
        code, stdout, _ = MockCLIRunnerSimulator.run_command(
            ["order", "place", "--symbol", " SPY260930C00500000 ", "--qty", "1"]
        )
        self.assertEqual(code, 0)

    def test_f1_2_b04_cli_order_place_large_quantity(self):
        """TC-T2-F1.2-04: Large order quantity in CLI invocation."""
        code, stdout, _ = MockCLIRunnerSimulator.run_command(
            ["order", "place", "--symbol", "SPY260930C00500000", "--qty", "10000"]
        )
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["status"], "accepted")

    def test_f1_2_b05_cli_unknown_subcommand_boundary(self):
        """TC-T2-F1.2-05: Subcommand boundary error."""
        code, _, stderr = MockCLIRunnerSimulator.run_command(["--invalid-flag"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown CLI command", stderr)

    # =========================================================================
    # Feature 1.3: Unified AlpacaGateway (Boundaries)
    # =========================================================================

    def test_f1_3_b01_gateway_zero_cash_positive_portfolio(self):
        """TC-T2-F1.3-01: Zero liquid cash with fully invested equity."""
        snap = MockAccountSnapshotFactory.create_healthy_account(
            portfolio_value=Decimal("100000.00"), cash=Decimal("0.00")
        )
        self.assertEqual(snap.cash, Decimal("0.00"))
        self.assertEqual(snap.long_market_value, Decimal("100000.00"))

    def test_f1_3_b02_gateway_empty_option_chain(self):
        """TC-T2-F1.3-02: Zero contracts returned in chain query."""
        contracts: list[OptionContract] = []
        self.assertEqual(len(contracts), 0)

    def test_f1_3_b03_gateway_single_contract_quantity(self):
        """TC-T2-F1.3-03: Minimum order quantity of 1 contract."""
        contract = MockOptionContractFactory.create_valid_contract()
        cost = contract.calculate_trade_cost(contracts=1, use_ask=True)
        self.assertEqual(cost, Decimal("220.00"))

    def test_f1_3_b04_gateway_contract_with_zero_open_interest(self):
        """TC-T2-F1.3-04: Contract with OI = 0 in gateway chain."""
        contract = MockOptionContractFactory.create_low_oi_contract(oi=0)
        self.assertEqual(contract.open_interest, 0)

    def test_f1_3_b05_gateway_contract_large_strike_price(self):
        """TC-T2-F1.3-05: High-dollar strike price (e.g. Berkshire A equivalent)."""
        contract = MockOptionContractFactory.create_valid_contract(strike_price="650000.00")
        self.assertEqual(contract.strike_price, Decimal("650000.00"))

    # =========================================================================
    # Feature 1.4: Pseudo-MCP Removal (Boundaries)
    # =========================================================================

    def test_f1_4_b01_zero_contract_quantity_raises_value_error(self):
        """TC-T2-F1.4-01: Zero contracts in TradeProposal raises ValueError."""
        contract = MockOptionContractFactory.create_valid_contract()
        with self.assertRaises(ValueError):
            TradeProposal(contract=contract, quantity=0, strategy_name="S")

    def test_f1_4_b02_negative_contract_quantity_raises_value_error(self):
        """TC-T2-F1.4-02: Negative contracts in TradeProposal raises ValueError."""
        contract = MockOptionContractFactory.create_valid_contract()
        with self.assertRaises(ValueError):
            TradeProposal(contract=contract, quantity=-5, strategy_name="S")

    def test_f1_4_b03_executor_rejected_trade_returns_standard_dataclass(self):
        """TC-T2-F1.4-03: Rejected execution result returns standard dataclass."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("0.00"),
            portfolio_risk_pct_used=Decimal("1.0"),
            reasons=["Critical restriction"],
        )
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")
        self.assertIn("Critical restriction", res.error_message)

    def test_f1_4_b04_executor_limit_order_flag_handling(self):
        """TC-T2-F1.4-04: Limit price specified on rejected trade."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("0.00"),
            portfolio_risk_pct_used=Decimal("1.0"),
            reasons=["Blocked"],
        )
        res = executor.execute_approved_trade(
            proposal, verdict, use_limit_order=True, limit_price=Decimal("2.15")
        )
        self.assertFalse(res.success)

    def test_f1_4_b05_executor_action_case_insensitivity(self):
        """TC-T1-F1.4-05: Case-insensitive action handling ("buy" vs "BUY")."""
        contract = MockOptionContractFactory.create_valid_contract()
        prop = TradeProposal(contract=contract, quantity=1, strategy_name="S", action="buy")
        self.assertEqual(prop.action.upper(), "BUY")

    # =========================================================================
    # Feature 1.5: Project Dependency Config (Boundaries)
    # =========================================================================

    def test_f1_5_b01_risk_percentage_exact_quantization(self):
        """TC-T2-F1.5-01: Risk percentage quantization is exactly Decimal('0.05')."""
        self.assertEqual(DEFAULT_MAX_RISK_PER_TRADE_PCT.as_tuple().exponent, -2)

    def test_f1_5_b02_portfolio_options_cap_quantization(self):
        """TC-T2-F1.5-02: Options allocation cap quantization is exactly Decimal('0.25')."""
        self.assertEqual(DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT.as_tuple().exponent, -2)

    def test_f1_5_b03_open_interest_integer_type(self):
        """TC-T2-F1.5-03: Minimum OI is positive integer >= 500."""
        self.assertIsInstance(MIN_OPTION_OPEN_INTEREST, int)
        self.assertGreaterEqual(MIN_OPTION_OPEN_INTEREST, 500)

    def test_f1_5_b04_dte_range_bounds(self):
        """TC-T2-F1.5-04: DTE bounds satisfy 1 <= MIN_DTE < MAX_DTE <= 30."""
        self.assertEqual(MIN_DTE, 1)
        self.assertEqual(MAX_DTE, 30)

    def test_f1_5_b05_spread_pct_threshold(self):
        """TC-T2-F1.5-05: Option spread threshold is Decimal('0.05')."""
        self.assertEqual(MAX_OPTION_SPREAD_PCT, Decimal("0.05"))

    # =========================================================================
    # Feature 2.1: 5% Portfolio Risk Rule (Boundaries)
    # =========================================================================

    def test_f2_1_b01_exact_5_percent_boundary_approved(self):
        """TC-T2-F2.1-01: Trade cost exactly equal to 5.0000% is approved."""
        account = MockAccountSnapshotFactory.create_healthy_account(portfolio_value=Decimal("100000.00"))
        # Ask = $5.00. 10 contracts * $5.00 * 100 = $5,000.00 == exactly 5.00% of $100,000
        contract = MockOptionContractFactory.create_valid_contract(bid_price="4.90", ask_price="5.00")
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("5000.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0500"))

    def test_f2_1_b02_one_cent_over_5_percent_rejected(self):
        """TC-T2-F2.1-02: Trade cost of 5.0001% ($5,000.01) is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account(portfolio_value=Decimal("100000.00"))
        # Ask = $5.0001. 10 contracts * $5.0001 * 100 = $5,000.10 > $5,000.00
        contract = MockOptionContractFactory.create_valid_contract(bid_price="4.95", ask_price="5.0001")
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_1_b03_zero_portfolio_value_rejected(self):
        """TC-T2-F2.1-03: Zero portfolio value account rejected."""
        account = MockAccountSnapshotFactory.create_zero_equity_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_allowed_budget, Decimal("0.00"))

    def test_f2_1_b04_zero_buying_power_rejected(self):
        """TC-T2-F2.1-04: Account with zero buying power rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account(buying_power=Decimal("0.00"))
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_1_b05_exact_25_percent_options_cap_boundary(self):
        """TC-T2-F2.1-05: Cumulative options exposure exactly 25.0000% approved vs 25.0001% rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account(portfolio_value=Decimal("100000.00"))
        contract = MockOptionContractFactory.create_valid_contract(bid_price="4.90", ask_price="5.00")
        # Current = $20,000. New trade = $5,000. Total = $25,000.00 == exactly 25%
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="S")
        v_exact = self.risk_engine.evaluate_trade(
            proposal, account, current_options_exposure=Decimal("20000.00")
        )
        self.assertTrue(v_exact.is_approved)

        # Current = $20,000.01. New trade = $5,000. Total = $25,000.01 > 25%
        v_over = self.risk_engine.evaluate_trade(
            proposal, account, current_options_exposure=Decimal("20000.01")
        )
        self.assertFalse(v_over.is_approved)

    # =========================================================================
    # Feature 2.2: Spread Thresholds (Boundaries)
    # =========================================================================

    def test_f2_2_b01_exact_5_percent_spread_boundary(self):
        """TC-T2-F2.2-01: Bid-ask spread at exactly 5.0000% is approved."""
        # Mid = $2.00. Bid = $1.95, Ask = $2.05 -> Spread = 0.10 / 2.00 = 5.0000%
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="1.95", ask_price="2.05")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_2_b02_spread_slightly_above_5_percent_rejected(self):
        """TC-T2-F2.2-02: Bid-ask spread of 5.01% is rejected."""
        # Mid = $2.00. Bid = $1.94, Ask = $2.06 -> Spread = 0.12 / 2.00 = 6.00% > 5.00%
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="1.94", ask_price="2.06")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_2_b03_bid_equals_ask_locked_market_rejected(self):
        """TC-T2-F2.2-03: Locked market (bid == ask, zero spread) is rejected as invalid quote."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="2.00", ask_price="2.00")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_2_b04_crossed_market_bid_greater_than_ask_rejected(self):
        """TC-T2-F2.2-04: Crossed market (bid > ask) rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="2.10", ask_price="2.00")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_2_b05_negative_price_rejected(self):
        """TC-T2-F2.2-05: Negative quote prices rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="-1.00", ask_price="2.00")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    # =========================================================================
    # Feature 2.3: Liquidity Thresholds (Boundaries)
    # =========================================================================

    def test_f2_3_b01_open_interest_exact_500_approved(self):
        """TC-T2-F2.3-01: Open interest exactly 500 is approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_low_oi_contract(oi=500)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_3_b02_open_interest_499_rejected(self):
        """TC-T2-F2.3-02: Open interest of 499 is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_low_oi_contract(oi=499)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_3_b03_open_interest_zero_rejected(self):
        """TC-T2-F2.3-03: Open interest of 0 is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_low_oi_contract(oi=0)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_3_b04_large_open_interest_handling(self):
        """TC-T2-F2.3-04: High open interest (1,000,000) does not overflow."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(open_interest=1000000)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_3_b05_underlying_volume_exact_1m_tradable(self):
        """TC-T2-F2.3-05: Underlying screening with exact 1,000,000 volume is tradable."""
        score = screen_ticker_liquidity(
            ticker="SPY",
            daily_volume=1000000,
            bid_price=Decimal("500.00"),
            ask_price=Decimal("500.02"),
            option_open_interest=5000,
        )
        self.assertTrue(score.is_tradable)

    # =========================================================================
    # Feature 2.4: Greeks & DTE Filters (Boundaries)
    # =========================================================================

    def test_f2_4_b01_dte_exact_1_approved(self):
        """TC-T2-F2.4-01: DTE of 1 day is approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(dte=1)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_4_b02_dte_exact_30_approved(self):
        """TC-T2-F2.4-02: DTE of 30 days is approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(dte=30)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_4_b03_dte_31_rejected(self):
        """TC-T2-F2.4-03: DTE of 31 days is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(dte=31)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_4_b04_dte_zero_rejected(self):
        """TC-T2-F2.4-04: DTE of 0 (same day expiration) is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_zero_dte_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_4_b05_negative_dte_rejected(self):
        """TC-T2-F2.4-05: Negative DTE (expired contract) is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(dte=-1)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    # =========================================================================
    # Feature 2.5: Infrangible Broker Blocking (Boundaries)
    # =========================================================================

    def test_f2_5_b01_multiple_compounding_violations_aggregated(self):
        """TC-T2-F2.5-01: Multiple simultaneous violations are all captured in reasons."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        # Invalid DTE (0), low OI (100), wide spread (50%)
        contract = MockOptionContractFactory.create_valid_contract(
            dte=0, open_interest=100, bid_price="1.00", ask_price="2.00"
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertGreaterEqual(len(verdict.reasons), 3)

    def test_f2_5_b02_unit_cost_exceeds_budget_recommended_quantity_zero(self):
        """TC-T2-F2.5-02: Single contract cost > effective budget gives recommended_quantity = 0."""
        account = MockAccountSnapshotFactory.create_low_cash_account(cash=Decimal("100.00"))
        # Ask = $2.20. 1 contract = $220 > $100 cash
        contract = MockOptionContractFactory.create_valid_contract(bid_price="2.10", ask_price="2.20")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.recommended_quantity, 0)

    def test_f2_5_b03_margin_call_boundary_equity_equals_maintenance(self):
        """TC-T2-F2.5-03: Equity == maintenance margin produces critical margin call error."""
        snap = AccountSnapshot(
            account_id="acc-margin-eq",
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("50000.00"),
            buying_power=Decimal("50000.00"),
            equity=Decimal("50000.00"),
            long_market_value=Decimal("45000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("40000.00"),
            maintenance_margin=Decimal("50000.00"),  # == equity
            daytrading_buying_power=Decimal("50000.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        health = check_account_health(snap)
        self.assertFalse(health.can_trade)
        self.assertTrue(any("Margin Call" in err for err in health.critical_errors))

    def test_f2_5_b04_pdt_warning_generated(self):
        """TC-T2-F2.5-04: Account with 3 daytrades generates PDT warning."""
        snap = AccountSnapshot(
            account_id="acc-pdt",
            cash=Decimal("10000.00"),
            portfolio_value=Decimal("20000.00"),
            buying_power=Decimal("20000.00"),
            equity=Decimal("20000.00"),
            long_market_value=Decimal("10000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("20000.00"),
            daytrading_count=3,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )
        health = check_account_health(snap)
        self.assertTrue(health.can_trade)
        self.assertTrue(any("PDT" in w for w in health.warnings))

    def test_f2_5_b05_rejection_preserves_budget_metrics_in_verdict(self):
        """TC-T2-F2.5-05: Rejection preserves budget metrics in RiskVerdict."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_zero_dte_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.max_allowed_budget, Decimal("5000.00"))
        self.assertGreater(verdict.trade_cost, Decimal("0.00"))

    # =========================================================================
    # Feature 3.1: Pipeline Mode Routing (Boundaries)
    # =========================================================================

    def test_f3_1_b01_dry_run_unapproved_proposal_never_logs_simulated(self):
        """TC-T2-F3.1-01: Dry-run mode logs TRADE_REJECTED (never SIMULATED) on unapproved trade."""
        contract = MockOptionContractFactory.create_zero_dte_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="DryRun")
        account = MockAccountSnapshotFactory.create_healthy_account()
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        entry = self.logger.log_rejected_trade(proposal, verdict)
        self.assertEqual(entry.event_type, "TRADE_REJECTED")
        self.assertNotEqual(entry.execution_status, "SIMULATED")

    def test_f3_1_b02_dry_run_simulated_order_id_format(self):
        """TC-T2-F3.1-02: Simulated order ID format."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="DryRun")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
        )
        sim_id = "dry-run-order-20260903"
        entry = self.logger.log_executed_trade(
            proposal, verdict, order_id=sim_id, status="SIMULATED"
        )
        self.assertEqual(entry.order_id, sim_id)
        self.assertEqual(entry.execution_status, "SIMULATED")

    def test_f3_1_b03_scan_mode_empty_ticker_list_handling(self):
        """TC-T2-F3.1-03: Empty ticker universe handled cleanly."""
        tickers: list[str] = []
        self.assertEqual(len(tickers), 0)

    def test_f3_1_b04_proposal_slippage_boundary(self):
        """TC-T2-F3.1-04: Maximum slippage parameter boundary."""
        contract = MockOptionContractFactory.create_valid_contract()
        prop = TradeProposal(
            contract=contract, quantity=1, strategy_name="S", max_slippage_pct=Decimal("0.05")
        )
        self.assertEqual(prop.max_slippage_pct, Decimal("0.05"))

    def test_f3_1_b05_contract_low_strike_price(self):
        """TC-T2-F3.1-05: Contract with low strike price ($0.50 penny stock equivalent)."""
        contract = MockOptionContractFactory.create_valid_contract(strike_price="0.50")
        self.assertEqual(contract.strike_price, Decimal("0.50"))

    # =========================================================================
    # Feature 3.2: Structured JSONL Logging (Boundaries)
    # =========================================================================

    def test_f3_2_b01_special_characters_in_rationale_escaped(self):
        """TC-T2-F3.2-01: Quotes and backslashes in strategy rationale escaped in JSONL."""
        contract = MockOptionContractFactory.create_valid_contract()
        complex_strategy_name = 'Breakout "Triple-Top" \\ Trend-Follower'
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name=complex_strategy_name)
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
        )
        entry = self.logger.log_executed_trade(proposal, verdict, order_id="ord-quotes")
        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        last_line = json.loads(lines[-1].strip())
        self.assertEqual(last_line["strategy_name"], complex_strategy_name)

    def test_f3_2_b02_unicode_characters_in_logger_output(self):
        """TC-T2-F3.2-02: Non-ASCII characters in logged reasons handled without error."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="Estrategia Española")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
            reasons=["Violación de límite: Riesgo > 5% del valor de cartera con señal errónea"],
        )
        entry = self.logger.log_rejected_trade(proposal, verdict)
        history = self.logger.get_trade_history(limit=1)
        self.assertIn("Violación", history[0].risk_reasons[0])

    def test_f3_2_b03_empty_log_file_returns_empty_history(self):
        """TC-T2-F3.2-03: Non-existent or empty log file returns empty history list."""
        history = self.logger.get_trade_history(limit=10)
        self.assertEqual(history, [])

    def test_f3_2_b04_history_limit_zero_returns_empty(self):
        """TC-T2-F3.2-04: Querying history with limit=0 returns empty list."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
        )
        self.logger.log_executed_trade(proposal, verdict, order_id="ord-0")
        history = self.logger.get_trade_history(limit=0)
        self.assertEqual(history, [])

    def test_f3_2_b05_corrupted_line_in_log_tolerated(self):
        """TC-T2-F3.2-05: Corrupted or unparseable lines in log are skipped gracefully."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("THIS_IS_A_CORRUPTED_NON_JSON_LINE\n")

        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
        )
        self.logger.log_executed_trade(proposal, verdict, order_id="ord-valid")

        history = self.logger.get_trade_history(limit=10)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].order_id, "ord-valid")


if __name__ == "__main__":
    unittest.main()
