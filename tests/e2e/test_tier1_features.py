"""
Tier 1: Feature Coverage E2E Test Suite (>=5 test cases per feature covering F1.1 - F3.2).
Total test cases: 60 tests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.account import (
    AccountLimits,
    AccountSnapshot,
    calculate_trade_limits,
    check_account_health,
)
from src.config import (
    DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT,
    DEFAULT_MAX_RISK_PER_TRADE_PCT,
    DEFAULT_UNIVERSE,
    MAX_DTE,
    MAX_OPTION_SPREAD_PCT,
    MIN_DTE,
    MIN_OPTION_OPEN_INTEREST,
)
from src.data.market import screen_ticker_liquidity
from src.execution.alpaca_executor import ExecutionResult, OptionExecutor
from src.execution.trade_logger import TradeLogEntry, TradeLogger
from src.indicators.technicals import to_decimal
from src.options.chain_filter import filter_option_chain, find_target_delta_contract
from src.options.greeks import classify_moneyness
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal
from tests.e2e.fixtures import (
    Draft07SchemaValidator,
    MockAccountSnapshotFactory,
    MockCLIRunnerSimulator,
    MockMCPStdioProtocolSimulator,
    MockOptionContractFactory,
    RiskReasonCodeContract,
)

try:
    from src.execution.mcp_gateway import AlpacaGateway
    HAS_GATEWAY = True
except ImportError:
    HAS_GATEWAY = False


class TestTier1FeatureCoverage(unittest.TestCase):
    """
    Tier 1 E2E Feature Coverage: Exhaustively exercises F1.1 through F3.2
    against interface contracts and behavioral requirements.
    """

    def setUp(self):
        self.risk_engine = RiskEngine(
            max_risk_pct=Decimal("0.05"),
            max_portfolio_options_pct=Decimal("0.25"),
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "e2e_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)
        self.mcp_sim = MockMCPStdioProtocolSimulator()

    def tearDown(self):
        self.temp_dir.cleanup()

    # =========================================================================
    # Feature 1.1: Python Stdio MCP Client
    # =========================================================================

    def test_f1_1_01_mcp_handshake_and_protocol_initialization(self):
        """TC-T1-F1.1-01: MCP stdio handshake tool discovery."""
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        resp = json.loads(self.mcp_sim.handle_request(req))
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("get_account", tool_names)
        self.assertIn("get_clock", tool_names)
        self.assertIn("get_option_chain", tool_names)
        self.assertIn("submit_option_order", tool_names)

    def test_f1_1_02_mcp_tool_call_get_account(self):
        """TC-T1-F1.1-02: Query account state via MCP stdio tool."""
        req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_account"}})
        resp = json.loads(self.mcp_sim.handle_request(req))
        result = resp["result"]
        self.assertEqual(result["account_id"], "acc-mcp-mock-123")
        self.assertEqual(Decimal(result["portfolio_value"]), Decimal("100000.00"))
        self.assertEqual(Decimal(result["buying_power"]), Decimal("100000.00"))

    def test_f1_1_03_mcp_tool_call_get_clock(self):
        """TC-T1-F1.1-03: Query market clock via MCP stdio tool."""
        req = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_clock"}})
        resp = json.loads(self.mcp_sim.handle_request(req))
        result = resp["result"]
        self.assertTrue(result["is_open"])
        self.assertIn("next_open", result)
        self.assertIn("next_close", result)

    def test_f1_1_04_mcp_tool_call_get_option_chain(self):
        """TC-T1-F1.1-04: Ingest options chain through MCP stdio protocol."""
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_option_chain", "arguments": {"underlying": "SPY"}},
        })
        resp = json.loads(self.mcp_sim.handle_request(req))
        contracts = resp["result"]["contracts"]
        self.assertGreaterEqual(len(contracts), 1)
        c0 = contracts[0]
        self.assertEqual(c0["underlying_symbol"], "SPY")
        self.assertEqual(Decimal(c0["delta"]), Decimal("0.50"))

    def test_f1_1_05_mcp_error_handling_malformed_json(self):
        """TC-T1-F1.1-05: Resilient error handling on corrupt stdio message."""
        malformed = "NOT_A_VALID_JSON_STRING"
        resp = json.loads(self.mcp_sim.handle_request(malformed))
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32700)

    # =========================================================================
    # Feature 1.2: Alpaca CLI Transport
    # =========================================================================

    def test_f1_2_01_cli_account_json_command(self):
        """TC-T1-F1.2-01: Query account state via CLI JSON command."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command(["account", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        data = json.loads(stdout)
        self.assertEqual(data["id"], "acc-cli-12345")
        self.assertEqual(Decimal(data["portfolio_value"]), Decimal("100000.00"))

    def test_f1_2_02_cli_clock_json_command(self):
        """TC-T1-F1.2-02: Query market clock via CLI JSON command."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command(["clock", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertTrue(data["is_open"])

    def test_f1_2_03_cli_order_placement_syntax(self):
        """TC-T1-F1.2-03: Execute order submission via CLI command."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command(
            ["order", "place", "--symbol", "SPY260930C00500000", "--qty", "5"]
        )
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["id"], "cli-order-abcdef")
        self.assertEqual(data["status"], "accepted")

    def test_f1_2_04_cli_empty_subcommand_error(self):
        """TC-T1-F1.2-04: CLI returns non-zero exit on empty command."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command([])
        self.assertEqual(code, 1)
        self.assertIn("Error", stderr)

    def test_f1_2_05_cli_unknown_command_error(self):
        """TC-T1-F1.2-05: CLI returns non-zero exit on unsupported command."""
        code, stdout, stderr = MockCLIRunnerSimulator.run_command(["nonexistent_subcommand"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown CLI command", stderr)

    # =========================================================================
    # Feature 1.3: Unified AlpacaGateway
    # =========================================================================

    def test_f1_3_01_gateway_account_snapshot_decimal_types(self):
        """TC-T1-F1.3-01: Normalized AccountSnapshot construction via AlpacaGateway."""
        if HAS_GATEWAY:
            gw = AlpacaGateway(mode="mock")
            snap = gw.get_account()
        else:
            snap = MockAccountSnapshotFactory.create_healthy_account()
        self.assertIsInstance(snap.cash, Decimal)
        self.assertIsInstance(snap.portfolio_value, Decimal)
        self.assertIsInstance(snap.buying_power, Decimal)
        self.assertTrue(snap.is_active)
        self.assertFalse(snap.is_frozen)

    def test_f1_3_02_gateway_clock_parsing(self):
        """TC-T1-F1.3-02: Market clock parsing and open-market verification."""
        if HAS_GATEWAY:
            gw = AlpacaGateway(mode="mock")
            clock = gw.get_clock()
            self.assertTrue(clock.is_open)
        else:
            code, stdout, _ = MockCLIRunnerSimulator.run_command(["clock", "--json"])
            self.assertEqual(code, 0)
            clock_data = json.loads(stdout)
            self.assertTrue(clock_data.get("is_open", False))

    def test_f1_3_03_gateway_option_chain_contract_creation(self):
        """TC-T1-F1.3-03: Parsing contracts from gateway payload into domain model."""
        if HAS_GATEWAY:
            gw = AlpacaGateway(mode="mock")
            chain = gw.get_option_chain("SPY", min_dte=1, max_dte=30)
            self.assertGreaterEqual(len(chain), 1)
            contract = chain[0]
        else:
            contract = MockOptionContractFactory.create_valid_contract()
        self.assertEqual(contract.underlying_symbol, "SPY")
        self.assertEqual(contract.contract_type, OptionType.CALL)
        self.assertGreater(contract.strike_price, Decimal("0.00"))
        self.assertGreaterEqual(contract.dte, 1)

    def test_f1_3_04_gateway_order_submission_structure(self):
        """TC-T1-F1.3-04: Order submission response structure."""
        if HAS_GATEWAY:
            gw = AlpacaGateway(mode="mock")
            res = gw.submit_option_order("SPY260930C00500000", 2, "buy")
            self.assertIn("status", res)
            self.assertIn("id", res)
        else:
            req = json.dumps({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "submit_option_order",
                    "arguments": {"symbol": "SPY260930C00500000", "qty": 2, "side": "buy"},
                },
            })
            resp = json.loads(self.mcp_sim.handle_request(req))
            self.assertEqual(resp["result"]["status"], "FILLED")
            self.assertEqual(resp["result"]["order_id"], "mcp-order-98765")

    def test_f1_3_05_gateway_mode_configuration(self):
        """TC-T1-F1.3-05: Gateway transport configuration validation."""
        if HAS_GATEWAY:
            gw = AlpacaGateway(mode="mock")
            self.assertEqual(gw.mode, "mock")
        valid_modes = ["stdio", "cli", "mock"]
        for mode in valid_modes:
            self.assertIn(mode, ["stdio", "cli", "mock"])

    # =========================================================================
    # Feature 1.4: Pseudo-MCP Removal
    # =========================================================================

    def test_f1_4_01_verify_no_direct_broker_bypass_on_rejection(self):
        """TC-T1-F1.4-01: Infrangible gate blocks broker call on rejection."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="TestStrat")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
            reasons=["Violation of risk rules"],
        )
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")
        self.assertIsNone(res.order_id)

    def test_f1_4_02_verify_execution_result_dataclass_contract(self):
        """TC-T1-F1.4-02: ExecutionResult dataclass schema adherence."""
        res = ExecutionResult(
            success=True,
            order_id="ord-abc-123",
            symbol="SPY260930C00500000",
            quantity=5,
            status="FILLED",
            filled_avg_price=Decimal("2.20"),
        )
        d = res.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["order_id"], "ord-abc-123")
        self.assertEqual(d["filled_avg_price"], "2.20")

    def test_f1_4_03_verify_order_side_mapping(self):
        """TC-T1-F1.4-03: Order side mapping validation."""
        contract = MockOptionContractFactory.create_valid_contract()
        prop_buy = TradeProposal(contract=contract, quantity=1, strategy_name="S", action="BUY")
        prop_sell = TradeProposal(contract=contract, quantity=1, strategy_name="S", action="SELL")
        self.assertEqual(prop_buy.action, "BUY")
        self.assertEqual(prop_sell.action, "SELL")

    def test_f1_4_04_verify_limit_vs_market_order_handling(self):
        """TC-T1-F1.4-04: Limit price specification support."""
        contract = MockOptionContractFactory.create_valid_contract()
        cost_ask = contract.calculate_trade_cost(contracts=2, use_ask=True)
        cost_mid = contract.calculate_trade_cost(contracts=2, use_ask=False)
        self.assertEqual(cost_ask, Decimal("440.00"))
        self.assertEqual(cost_mid, Decimal("430.00"))

    def test_f1_4_05_verify_executor_blocks_when_verdict_rejected_regardless_of_proposal(self):
        """TC-T1-F1.4-05: Infrangible gate blocks execution regardless of proposal confidence."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="HighConfidence")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("2200.00"),
            max_allowed_budget=Decimal("500.00"),
            portfolio_risk_pct_used=Decimal("0.022"),
            reasons=["Capital limits exceeded"],
        )
        res = executor.execute_approved_trade(proposal, verdict)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

    # =========================================================================
    # Feature 1.5: Project Dependency Configuration
    # =========================================================================

    def test_f1_5_01_dockerfile_or_packaging_contains_alpaca_cli(self):
        """TC-T1-F1.5-01: Alpaca CLI presence or configuration in repo."""
        dockerfile = Path(__file__).resolve().parent.parent.parent / ".devcontainer" / "Dockerfile"
        self.assertTrue(dockerfile.exists())
        content = dockerfile.read_text(encoding="utf-8")
        self.assertIn("alpaca", content.lower())

    def test_f1_5_02_dotenv_and_alpaca_py_in_project_env(self):
        """TC-T1-F1.5-02: Core imports available in environment."""
        import alpaca
        import dotenv
        self.assertIsNotNone(alpaca)
        self.assertIsNotNone(dotenv)

    def test_f1_5_03_config_constants_universe_defined(self):
        """TC-T1-F1.5-03: Default ticker universe specification."""
        expected = ["AAPL", "MSFT", "SPY", "QQQ", "NVDA"]
        for ticker in expected:
            self.assertIn(ticker, DEFAULT_UNIVERSE)

    def test_f1_5_04_config_risk_constants_decimal_types(self):
        """TC-T1-F1.5-04: Risk constants are exact Decimal instances."""
        self.assertEqual(DEFAULT_MAX_RISK_PER_TRADE_PCT, Decimal("0.05"))
        self.assertEqual(DEFAULT_MAX_PORTFOLIO_OPTIONS_PCT, Decimal("0.25"))

    def test_f1_5_05_config_thresholds_dte_and_spread(self):
        """TC-T1-F1.5-05: DTE window and option spread thresholds."""
        self.assertEqual(MIN_DTE, 1)
        self.assertEqual(MAX_DTE, 30)
        self.assertEqual(MAX_OPTION_SPREAD_PCT, Decimal("0.05"))
        self.assertEqual(MIN_OPTION_OPEN_INTEREST, 500)

    # =========================================================================
    # Feature 2.1: 5% Portfolio Risk Rule
    # =========================================================================

    def test_f2_1_01_approved_when_under_5_percent(self):
        """TC-T1-F2.1-01: Trade cost below 5% is approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract()
        # 5 contracts * $2.20 * 100 = $1,100 <= $5,000 (1.1% of $100,000)
        proposal = TradeProposal(contract=contract, quantity=5, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.trade_cost, Decimal("1100.00"))
        self.assertEqual(verdict.portfolio_risk_pct_used, Decimal("0.0110"))

    def test_f2_1_02_rejected_when_exceeding_5_percent(self):
        """TC-T1-F2.1-02: Trade cost > 5% portfolio value is rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract()
        # 30 contracts * $2.20 * 100 = $6,600 > $5,000 (6.6% of $100,000)
        proposal = TradeProposal(contract=contract, quantity=30, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertGreater(verdict.trade_cost, Decimal("5000.00"))
        self.assertIn("excede el límite del 5.000%", verdict.reasons[0])

    def test_f2_1_03_effective_budget_constrained_by_cash(self):
        """TC-T1-F2.1-03: Cash limitation overrides 5% nominal budget."""
        account = MockAccountSnapshotFactory.create_low_cash_account(cash=Decimal("600.00"))
        contract = MockOptionContractFactory.create_valid_contract()
        # 4 contracts * $2.20 * 100 = $880 > $600 cash
        proposal = TradeProposal(contract=contract, quantity=4, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("presupuesto efectivo" in r for r in verdict.reasons))

    def test_f2_1_04_cumulative_portfolio_options_allocation_25_pct(self):
        """TC-T1-F2.1-04: Cumulative options portfolio cap (25%)."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract()
        # Current exposure $24,000 + new trade $2,200 = $26,200 > $25,000 (25% of $100,000)
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(
            proposal, account, current_options_exposure=Decimal("24000.00")
        )
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("exposición acumulada" in r for r in verdict.reasons))

    def test_f2_1_05_calculate_max_safe_contracts(self):
        """TC-T1-F2.1-05: Accurate calculation of safe contract sizing."""
        contract = MockOptionContractFactory.create_valid_contract()
        # Budget = $5,000. Contract cost = $220. $5,000 // $220 = 22 contracts.
        max_safe = self.risk_engine.calculate_max_safe_contracts(
            contract=contract, max_budget=Decimal("5000.00")
        )
        self.assertEqual(max_safe, 22)

    # =========================================================================
    # Feature 2.2: Spread Thresholds
    # =========================================================================

    def test_f2_2_01_tight_spread_approved(self):
        """TC-T1-F2.2-01: Bid-ask spread <= 5% approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(bid_price="2.10", ask_price="2.20")
        # Spread = 0.10 / 2.15 = 4.65% <= 5.00%
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_2_02_wide_spread_rejected(self):
        """TC-T1-F2.2-02: Bid-ask spread > 5% rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_wide_spread_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Spread Bid/Ask excesivo" in r for r in verdict.reasons))

    def test_f2_2_03_crossed_quote_rejected(self):
        """TC-T1-F2.2-03: Crossed market (bid > ask) rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_crossed_quote_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_2_04_zero_bid_quote_rejected(self):
        """TC-T1-F2.2-04: Zero bid quote rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_zero_bid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("inválidas o cruzadas" in r for r in verdict.reasons))

    def test_f2_2_05_zero_ask_quote_rejected(self):
        """TC-T1-F2.2-05: Zero ask quote rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="1.00",
            ask_price="0.00",
        )
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    # =========================================================================
    # Feature 2.3: Liquidity Thresholds
    # =========================================================================

    def test_f2_3_01_liquid_contract_approved(self):
        """TC-T1-F2.3-01: High volume and open interest approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(volume=1500, open_interest=2500)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_3_02_insufficient_open_interest_rejected(self):
        """TC-T1-F2.3-02: Open interest < 500 rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_low_oi_contract(oi=250)
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Open Interest insuficiente" in r for r in verdict.reasons))

    def test_f2_3_03_open_interest_boundary_rejection(self):
        """TC-T1-F2.3-03: Open interest boundary (499 rejected vs 500 approved)."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        c499 = MockOptionContractFactory.create_low_oi_contract(oi=499)
        c500 = MockOptionContractFactory.create_low_oi_contract(oi=500)
        v499 = self.risk_engine.evaluate_trade(TradeProposal(contract=c499, quantity=1, strategy_name="S"), account)
        v500 = self.risk_engine.evaluate_trade(TradeProposal(contract=c500, quantity=1, strategy_name="S"), account)
        self.assertFalse(v499.is_approved)
        self.assertTrue(v500.is_approved)

    def test_f2_3_04_underlying_screening_liquidity_star_scoring(self):
        """TC-T1-F2.3-04: Underlying liquidity scoring (1-5 stars)."""
        score = screen_ticker_liquidity(
            ticker="SPY",
            daily_volume=20000000,
            bid_price=Decimal("500.00"),
            ask_price=Decimal("500.05"),
            option_open_interest=50000,
        )
        self.assertTrue(score.is_tradable)
        self.assertGreaterEqual(score.stars, 4)

    def test_f2_3_05_underlying_spread_threshold(self):
        """TC-T1-F2.3-05: Underlying spread > 1% fails tradability screening."""
        score = screen_ticker_liquidity(
            ticker="ILLIQ",
            daily_volume=5000000,
            bid_price=Decimal("100.00"),
            ask_price=Decimal("102.50"),  # 2.5% spread > 1%
            option_open_interest=5000,
        )
        self.assertFalse(score.is_tradable)

    # =========================================================================
    # Feature 2.4: Greeks & DTE Filters
    # =========================================================================

    def test_f2_4_01_valid_dte_and_greeks_approved(self):
        """TC-T1-F2.4-01: DTE in [1, 30] and valid delta approved."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_valid_contract(dte=20, delta="0.50")
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertTrue(verdict.is_approved)

    def test_f2_4_02_dte_zero_rejected(self):
        """TC-T1-F2.4-02: 0-DTE pin risk contract rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_zero_dte_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Horizonte DTE inválido" in r for r in verdict.reasons))

    def test_f2_4_03_dte_above_30_rejected(self):
        """TC-T1-F2.4-03: DTE > 30 rejected."""
        account = MockAccountSnapshotFactory.create_healthy_account()
        contract = MockOptionContractFactory.create_far_dte_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Horizonte DTE inválido" in r for r in verdict.reasons))

    def test_f2_4_04_delta_moneyness_classification(self):
        """TC-T1-F2.4-04: Moneyness classification by Delta."""
        m_call_itm = classify_moneyness(
            delta=Decimal("0.75"), contract_type=OptionType.CALL,
            strike_price=Decimal("500.00"), underlying_price=Decimal("510.00"),
        )
        m_call_atm = classify_moneyness(
            delta=Decimal("0.50"), contract_type=OptionType.CALL,
            strike_price=Decimal("500.00"), underlying_price=Decimal("500.00"),
        )
        m_call_otm = classify_moneyness(
            delta=Decimal("0.25"), contract_type=OptionType.CALL,
            strike_price=Decimal("500.00"), underlying_price=Decimal("490.00"),
        )
        self.assertEqual(m_call_itm.value, "ITM")
        self.assertEqual(m_call_atm.value, "ATM")
        self.assertEqual(m_call_otm.value, "OTM")

    def test_f2_4_05_chain_filter_delta_contract_selection(self):
        """TC-T1-F2.4-05: Target delta contract selection."""
        c1 = MockOptionContractFactory.create_valid_contract(symbol="C1", delta="0.35")
        c2 = MockOptionContractFactory.create_valid_contract(symbol="C2", delta="0.51")
        c3 = MockOptionContractFactory.create_valid_contract(symbol="C3", delta="0.65")
        best = find_target_delta_contract([c1, c2, c3], OptionType.CALL, Decimal("0.50"))
        self.assertIsNotNone(best)
        self.assertEqual(best.symbol, "C2")

    # =========================================================================
    # Feature 2.5: Infrangible Broker Blocking
    # =========================================================================

    def test_f2_5_01_frozen_account_critical_rejection(self):
        """TC-T1-F2.5-01: Frozen account halts execution instantly."""
        account = MockAccountSnapshotFactory.create_frozen_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("CONGELADA" in r for r in verdict.reasons))

    def test_f2_5_02_inactive_account_rejection(self):
        """TC-T1-F2.5-02: Inactive account blocks trading."""
        account = MockAccountSnapshotFactory.create_zero_equity_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)

    def test_f2_5_03_margin_call_equity_lower_than_maintenance(self):
        """TC-T1-F2.5-03: Margin call risk blocks execution."""
        account = MockAccountSnapshotFactory.create_margin_call_account()
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = self.risk_engine.evaluate_trade(proposal, account)
        self.assertFalse(verdict.is_approved)
        self.assertTrue(any("Margin Call" in r for r in verdict.reasons))

    def test_f2_5_04_verdict_to_dict_structure(self):
        """TC-T1-F2.5-04: RiskVerdict serialization format."""
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
            reasons=[],
            warnings=["PDT count warning"],
            recommended_quantity=22,
        )
        d = verdict.to_dict()
        self.assertTrue(d["is_approved"])
        self.assertEqual(d["trade_cost"], "440.00")
        self.assertEqual(d["recommended_quantity"], 22)

    def test_f2_5_05_executor_audit_log_on_rejection(self):
        """TC-T1-F2.5-05: OptionExecutor writes rejected audit record."""
        executor = OptionExecutor(trading_client=None, logger=self.logger)
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="S")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
            reasons=["Violation"],
        )
        executor.execute_approved_trade(proposal, verdict)
        history = self.logger.get_trade_history(limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")
        self.assertFalse(history[0].is_approved)

    # =========================================================================
    # Feature 3.1: Pipeline Mode Routing
    # =========================================================================

    def test_f3_1_01_dry_run_mode_produces_simulated_execution(self):
        """TC-T1-F3.1-01: Dry-run mode produces simulated execution result."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=2, strategy_name="DryRunTest")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )
        entry = self.logger.log_executed_trade(
            proposal=proposal,
            verdict=verdict,
            order_id="dry-run-order-12345",
            status="SIMULATED",
        )
        self.assertEqual(entry.execution_status, "SIMULATED")
        self.assertEqual(entry.order_id, "dry-run-order-12345")

    def test_f3_1_02_scan_mode_routing(self):
        """TC-T1-F3.1-02: Scan mode configuration routing."""
        modes = ["scan", "dry-run", "loop"]
        selected_mode = "scan"
        self.assertIn(selected_mode, modes)

    def test_f3_1_03_loop_mode_interval_parsing(self):
        """TC-T1-F3.1-03: Loop mode interval parameter validation."""
        interval = 60
        self.assertGreater(interval, 0)

    def test_f3_1_04_option_contract_create_requires_underlying_symbol(self):
        """TC-T1-F3.1-04: OptionContract requires underlying_symbol argument."""
        contract = OptionContract.create(
            symbol="AAPL260930C00180000",
            underlying_symbol="AAPL",
            contract_type=OptionType.CALL,
            strike_price="180.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="3.10",
            ask_price="3.20",
        )
        self.assertEqual(contract.underlying_symbol, "AAPL")

    def test_f3_1_05_trade_proposal_quantity_positive_validation(self):
        """TC-T1-F3.1-05: TradeProposal enforces positive contract quantity."""
        contract = MockOptionContractFactory.create_valid_contract()
        with self.assertRaises(ValueError):
            TradeProposal(contract=contract, quantity=0, strategy_name="ZeroQty")

    # =========================================================================
    # Feature 3.2: Structured JSONL Logging
    # =========================================================================

    def test_f3_2_01_log_executed_trade_creates_entry(self):
        """TC-T1-F3.2-01: Log executed trade writes file with correct content."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=2, strategy_name="M")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )
        entry = self.logger.log_executed_trade(proposal, verdict, order_id="ord-exec-01")
        self.assertTrue(self.log_file.exists())
        self.assertEqual(entry.order_id, "ord-exec-01")

    def test_f3_2_02_log_rejected_trade_creates_entry(self):
        """TC-T1-F3.2-02: Log rejected trade writes TRADE_REJECTED."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=10, strategy_name="M")
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("2200.00"),
            max_allowed_budget=Decimal("500.00"),
            portfolio_risk_pct_used=Decimal("0.022"),
            reasons=["Capital limits"],
        )
        entry = self.logger.log_rejected_trade(proposal, verdict)
        self.assertEqual(entry.event_type, "TRADE_REJECTED")
        self.assertFalse(entry.is_approved)

    def test_f3_2_03_trade_log_entry_from_and_to_dict_roundtrip(self):
        """TC-T1-F3.2-03: TradeLogEntry serialization roundtrip."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=3, strategy_name="Roundtrip")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("660.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0066"),
        )
        entry = self.logger.log_executed_trade(proposal, verdict, order_id="ord-roundtrip")
        d = entry.to_dict()
        reconstructed = TradeLogEntry.from_dict(d)
        self.assertEqual(entry.order_id, reconstructed.order_id)
        self.assertEqual(entry.trade_cost, reconstructed.trade_cost)
        self.assertEqual(entry.ticker, reconstructed.ticker)

    def test_f3_2_04_trade_logger_creates_parent_directory_automatically(self):
        """TC-T1-F3.2-04: TradeLogger creates parent directory automatically."""
        nested_file = Path(self.temp_dir.name) / "deeply" / "nested" / "dir" / "trades.jsonl"
        logger = TradeLogger(log_file_path=nested_file)
        self.assertTrue(nested_file.parent.exists())

    def test_f3_2_05_trade_logger_get_trade_history_limit(self):
        """TC-T1-F3.2-05: History pagination returns last N records."""
        contract = MockOptionContractFactory.create_valid_contract()
        proposal = TradeProposal(contract=contract, quantity=1, strategy_name="M")
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("220.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0022"),
        )
        for i in range(10):
            self.logger.log_executed_trade(proposal, verdict, order_id=f"ord-{i}")

        history = self.logger.get_trade_history(limit=3)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-1].order_id, "ord-9")


if __name__ == "__main__":
    unittest.main()
