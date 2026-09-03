"""
Pruebas Unitarias para Capa de Ejecución, Trade Logger y MCP Tools (Features F1.3, F1.4, F3.1 & F3.2).
"""

from __future__ import annotations

import json
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
    mcp_get_account_snapshot,
    mcp_get_screened_universe,
)
from src.execution.mcp_gateway import AlpacaGateway
from src.execution.trade_logger import TradeLogEntry, TradeLogger
from src.options.models import OptionContract, OptionType
from src.risk.models import RiskReasonCode
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal
from tests.e2e.fixtures import Draft07SchemaValidator


class TestTradeLogger(unittest.TestCase):
    """Pruebas del gestor de bitácora y auditoría de trades (JSONL Draft-07)."""

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
            volume=2000,
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
            reason_code=RiskReasonCode.ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT,
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

    def test_draft07_jsonl_serialization_and_roundtrip(self):
        """Verifica la serialización a diccionario y reconstrucción con from_dict."""
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )
        entry = self.logger.log_executed_trade(
            proposal=self.proposal,
            verdict=verdict,
            order_id="ord-roundtrip-456",
            fill_price=Decimal("2.20"),
        )

        d = entry.to_dict()
        self.assertIn("timestamp", d)
        self.assertIn("event_type", d)
        self.assertIn("mode", d)
        self.assertIn("market_data_snapshot", d)
        self.assertIn("agent_proposal", d)
        self.assertIn("risk_verdict", d)
        self.assertIn("execution_result", d)

        # Validación formal con Draft07SchemaValidator
        is_valid, errors = Draft07SchemaValidator.validate(d)
        self.assertTrue(is_valid, f"Errores en validación Draft-07: {errors}")

        # Roundtrip
        reconstructed = TradeLogEntry.from_dict(d)
        self.assertEqual(reconstructed.order_id, entry.order_id)
        self.assertEqual(reconstructed.trade_cost, entry.trade_cost)
        self.assertEqual(reconstructed.ticker, entry.ticker)
        self.assertEqual(reconstructed.execution_status, entry.execution_status)

    def test_trade_logger_creates_directory_and_handles_pagination(self):
        """Verifica la creación automática de directorios anidados y límite de paginación."""
        nested_file = Path(self.temp_dir.name) / "deep" / "sub" / "trades.jsonl"
        logger = TradeLogger(log_file_path=nested_file)
        self.assertTrue(nested_file.parent.exists())

        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )
        for i in range(10):
            logger.log_executed_trade(self.proposal, verdict, order_id=f"ord-{i}")

        paged = logger.get_trade_history(limit=4)
        self.assertEqual(len(paged), 4)
        self.assertEqual(paged[-1].order_id, "ord-9")

        # Límite 0 o negativo retorna lista vacía
        self.assertEqual(logger.get_trade_history(limit=0), [])
        self.assertEqual(logger.get_trade_history(limit=-5), [])


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

    def test_executor_successful_approved_trade_via_gateway(self):
        """Verifica la ejecución a través de AlpacaGateway."""
        mock_gateway = MagicMock(spec=AlpacaGateway)
        mock_gateway.submit_option_order.return_value = {
            "id": "gw-order-888",
            "client_order_id": "client-888",
            "status": "filled",
            "filled_avg_price": "2.20",
            "filled_qty": "2",
        }

        executor = OptionExecutor(gateway=mock_gateway, logger=self.logger)
        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )

        result = executor.execute_approved_trade(self.proposal, verdict)
        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "gw-order-888")
        self.assertEqual(result.status, "FILLED")
        mock_gateway.submit_option_order.assert_called_once()

    def test_executor_blocks_unapproved_trade_without_calling_api(self):
        mock_client = MagicMock()
        mock_gw = MagicMock(spec=AlpacaGateway)
        executor = OptionExecutor(gateway=mock_gw, trading_client=mock_client, logger=self.logger)

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
        mock_gw.submit_option_order.assert_not_called()

        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_REJECTED")

    def test_executor_dry_run_simulation_mode(self):
        """Verifica que el modo dry-run simula la ejecución sin realizar llamadas al broker."""
        mock_gateway = MagicMock(spec=AlpacaGateway)
        executor = OptionExecutor(gateway=mock_gateway, logger=self.logger, dry_run=True)

        verdict = RiskVerdict(
            is_approved=True,
            trade_cost=Decimal("440.00"),
            max_allowed_budget=Decimal("5000.00"),
            portfolio_risk_pct_used=Decimal("0.0044"),
        )

        result = executor.execute_approved_trade(self.proposal, verdict)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "SIMULATED")
        self.assertTrue(result.order_id.startswith("dry-run-order-"))
        self.assertEqual(result.filled_avg_price, self.contract.ask_price)

        # Cero mutaciones en broker
        mock_gateway.submit_option_order.assert_not_called()

        # Audit log registrado como SIMULATED
        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_SIMULATED")
        self.assertEqual(history[0].execution_status, "SIMULATED")

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

    def test_mcp_get_account_snapshot(self):
        mock_snapshot = AccountSnapshot(
            account_id="acc-test-123",
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
        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = mock_snapshot

        d = mcp_get_account_snapshot(gateway=mock_gw)
        self.assertEqual(d["account_id"], "acc-test-123")
        self.assertEqual(d["cash"], "50000.00")

    def test_mcp_get_screened_universe(self):
        stats = {
            "SPY": {"volume": "10000000", "bid": "500.00", "ask": "500.05", "open_interest": 5000}
        }
        res = mcp_get_screened_universe(stats_by_ticker=stats)
        self.assertIn("SPY", res)
        self.assertTrue(res["SPY"]["is_tradable"])

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
