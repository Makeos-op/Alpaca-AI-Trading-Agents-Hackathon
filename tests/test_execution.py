"""
Pruebas Unitarias para Capa de Ejecución, Trade Logger y MCP Tools (FT-MCP-02 & FT-AGT-06).
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.account import AccountSnapshot
from src.execution.alpaca_executor import (
    ExecutionResult,
    OptionExecutor,
    mcp_evaluate_and_execute_option_trade,
)
from src.execution.trade_logger import TradeLogEntry, TradeLogger
from src.options.models import OptionContract, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


class TestTradeLogger(unittest.TestCase):
    """Pruebas del gestor de bitácora y auditoría de trades (JSONL)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "test_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)

        self.contract = OptionContract.create(
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
            theta="-0.04",
            implied_volatility="0.1850",
        )

        self.proposal = TradeProposal(
            contract=self.contract,
            quantity=2,
            strategy_name="MomentumStrategy",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_log_executed_trade(self):
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )

        entry = self.logger.log_executed_trade(
            proposal=self.proposal,
            verdict=verdict,
            order_id="ord-abc-123",
            fill_price=Decimal("2.20"),
        )

        self.assertEqual(entry.event_type, "TRADE_EXECUTED")
        self.assertTrue(entry.is_approved)
        self.assertEqual(entry.order_id, "ord-abc-123")
        self.assertEqual(entry.fill_price, Decimal("2.20"))
        self.assertEqual(entry.trade_cost, Decimal("440.00"))

        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].option_symbol, "SPY260930C00500000")
        self.assertEqual(history[0].execution_status, "FILLED")

    def test_log_rejected_trade(self):
        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("6000.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0600"),
            reasons=["El costo ($6000.00) excede el límite del 5.0%"],
        )

        entry = self.logger.log_rejected_trade(
            proposal=self.proposal,
            verdict=verdict,
        )

        self.assertEqual(entry.event_type, "TRADE_REJECTED")
        self.assertFalse(entry.is_approved)
        self.assertIsNone(entry.order_id)
        self.assertEqual(entry.execution_status, "REJECTED")
        self.assertEqual(len(entry.risk_reasons), 1)

        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")


class TestOptionExecutor(unittest.TestCase):
    """Pruebas del ejecutor de órdenes de opciones y validación pre-trade."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "test_exec.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)

        self.contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            open_interest=1500,
        )

        self.proposal = TradeProposal(
            contract=self.contract,
            quantity=2,
            strategy_name="BullishCall",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_executor_successful_approved_trade(self):
        mock_client = MagicMock()
        mock_order = SimpleNamespace(
            id="order-alpaca-777",
            status="filled",
            filled_avg_price="2.20",
        )
        mock_client.submit_order.return_value = mock_order

        executor = OptionExecutor(trading_client=mock_client, logger=self.logger)

        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )

        result = executor.execute_approved_trade(self.proposal, verdict)
        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "order-alpaca-777")
        self.assertEqual(result.status, "FILLED")
        self.assertEqual(result.filled_avg_price, Decimal("2.20"))

        mock_client.submit_order.assert_called_once()

    def test_executor_blocks_unapproved_trade_without_calling_api(self):
        mock_client = MagicMock()
        executor = OptionExecutor(trading_client=mock_client, logger=self.logger)

        verdict = RiskVerdict(
            is_approved=False,
            trade_cost=Decimal("6000.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.06"),
            reasons=["Límite del 5% excedido"],
        )

        result = executor.execute_approved_trade(self.proposal, verdict)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("Límite del 5% excedido", result.error_message)

        mock_client.submit_order.assert_not_called()

        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")

    def test_executor_handles_api_exception(self):
        mock_client = MagicMock()
        mock_client.submit_order.side_effect = RuntimeError("Conexión rechazada por Alpaca")
        executor = OptionExecutor(trading_client=mock_client, logger=self.logger)

        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )

        result = executor.execute_approved_trade(self.proposal, verdict)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "ERROR")
        self.assertIn("Conexión rechazada por Alpaca", result.error_message)


class TestMCPTools(unittest.TestCase):
    """Pruebas de la interfaz de herramientas MCP para agentes."""

    def test_mcp_evaluate_and_execute_option_trade(self):
        contract_data = {
            "symbol": "SPY260930C00500000",
            "underlying_symbol": "SPY",
            "contract_type": "CALL",
            "strike_price": "500.00",
            "expiration_date": "2026-09-30",
            "dte": 20,
            "bid_price": "2.10",
            "ask_price": "2.20",
            "open_interest": 1500,
            "delta": "0.50",
        }

        mock_snapshot = AccountSnapshot(
            account_id="acc-mcp",
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

        mock_client = MagicMock()
        mock_client.submit_order.return_value = SimpleNamespace(
            id="order-mcp-999",
            status="filled",
            filled_avg_price="2.20",
        )

        temp_dir = tempfile.TemporaryDirectory()
        logger = TradeLogger(log_file_path=Path(temp_dir.name) / "mcp.jsonl")
        executor = OptionExecutor(trading_client=mock_client, logger=logger)

        res = mcp_evaluate_and_execute_option_trade(
            contract_data=contract_data,
            quantity=2,
            strategy_name="MCPTestStrategy",
            action="BUY",
            snapshot=mock_snapshot,
            risk_engine=RiskEngine(),
            executor=executor,
        )

        self.assertTrue(res["verdict"]["is_approved"])
        self.assertTrue(res["execution"]["success"])
        self.assertEqual(res["execution"]["order_id"], "order-mcp-999")
        temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
