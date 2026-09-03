"""
Pruebas Unitarias e Integradas para el Entry Point (src/main.py),
Modo Scalping (--mode scalp) y Modo Quick-Trade (--quick-trade).
"""

from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.account import AccountSnapshot, MarketClockInfo
from src.execution.alpaca_executor import ExecutionResult
from src.execution.mcp_gateway import AlpacaGateway
from src.execution.trade_logger import TradeLogger
from src.main import (
    get_equity_market_quote,
    get_scalp_bars,
    main,
    run_quick_trade,
    run_scalp_cycle,
    run_trading_cycle,
)
from src.options.models import OptionContract, OptionType
from src.risk.models import RiskReasonCode
from src.risk.risk_engine import RiskVerdict, TradeProposal


class TestMainArgumentParser(unittest.TestCase):
    """Verifica que el CLI parser soporte todos los argumentos requeridos."""

    def test_parser_mode_choices_include_scalp(self):
        """TC-MAIN-CLI-01: El argumento --mode debe incluir 'scalp' además de 'scan', 'loop', 'dry-run'."""
        with patch("sys.argv", ["main.py", "--mode", "scalp"]):
            with patch("src.main.run_scalp_cycle") as mock_scalp:
                main()
                mock_scalp.assert_called_once()

    def test_parser_quick_trade_flag(self):
        """TC-MAIN-CLI-02: El flag --quick-trade debe activar run_quick_trade."""
        with patch("sys.argv", ["main.py", "--quick-trade"]):
            with patch("src.main.run_quick_trade") as mock_quick:
                main()
                mock_quick.assert_called_once()

    def test_parser_quick_trade_with_dry_run(self):
        """TC-MAIN-CLI-03: --quick-trade con --mode dry-run debe pasar dry_run=True."""
        with patch("sys.argv", ["main.py", "--quick-trade", "--mode", "dry-run", "--tickers", "SPY"]):
            with patch("src.main.run_quick_trade") as mock_quick:
                main()
                mock_quick.assert_called_once_with(ticker="SPY", dry_run=True, asset_type="auto")

    def test_parser_backward_compatibility_scan(self):
        """TC-MAIN-CLI-04: --mode scan debe invocar run_trading_cycle con dry_run=False."""
        with patch("sys.argv", ["main.py", "--mode", "scan", "--tickers", "SPY"]):
            with patch("src.main.run_trading_cycle") as mock_scan:
                main()
                mock_scan.assert_called_once_with(universe=["SPY"], dry_run=False)

    def test_parser_backward_compatibility_dry_run(self):
        """TC-MAIN-CLI-05: --mode dry-run debe invocar run_trading_cycle con dry_run=True."""
        with patch("sys.argv", ["main.py", "--mode", "dry-run", "--tickers", "AAPL"]):
            with patch("src.main.run_trading_cycle") as mock_scan:
                main()
                mock_scan.assert_called_once_with(universe=["AAPL"], dry_run=True)


class TestScalpMarketDataAndQuotes(unittest.TestCase):
    """Verifica la generación de barras de alta frecuencia y cotizaciones con spread seguro."""

    def test_get_scalp_bars_1min(self):
        """TC-MAIN-MD-01: get_scalp_bars genera velas de 1Min válidas con Decimal."""
        bars = get_scalp_bars("SPY", timeframe="1Min", limit=30)
        self.assertGreaterEqual(len(bars), 30)
        self.assertIsInstance(bars[0].close, Decimal)
        self.assertGreater(bars[0].close, Decimal("0.0"))
        self.assertGreater(bars[0].volume, Decimal("0.0"))

    def test_get_scalp_bars_5min(self):
        """TC-MAIN-MD-02: get_scalp_bars genera velas de 5Min válidas."""
        bars = get_scalp_bars("AAPL", timeframe="5Min", limit=30)
        self.assertGreaterEqual(len(bars), 30)
        self.assertIsInstance(bars[0].close, Decimal)
        self.assertGreater(bars[0].close, Decimal("0.0"))

    def test_get_equity_market_quote_positive_and_uncrossed(self):
        """TC-MAIN-MD-03: get_equity_market_quote retorna ask >= bid > 0 con spread <= $0.50."""
        ref_price, ask_price, bid_price = get_equity_market_quote("SPY")
        self.assertGreater(ref_price, Decimal("0.0"))
        self.assertGreater(ask_price, Decimal("0.0"))
        self.assertGreater(bid_price, Decimal("0.0"))
        self.assertGreaterEqual(ask_price, bid_price)
        self.assertLessEqual(ask_price - bid_price, Decimal("0.50"))


class TestQuickTradeExecution(unittest.TestCase):
    """Verifica el flujo determinista de --quick-trade con validación de RiskEngine."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "quick_trade.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)

        self.mock_snapshot = AccountSnapshot(
            account_id="acc-quick-001",
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

        self.mock_clock = MarketClockInfo(
            is_open=True,
            next_open="2026-09-04T09:30:00-04:00",
            next_close="2026-09-03T16:00:00-04:00",
            timestamp="2026-09-03T14:00:00-04:00",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_quick_trade_success_dry_run(self):
        """TC-MAIN-QT-01: --quick-trade en modo dry-run ejecuta orden simulada y registra log."""
        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = self.mock_snapshot
        mock_gw.get_clock.return_value = self.mock_clock

        result = run_quick_trade(
            ticker="SPY",
            dry_run=True,
            logger=self.logger,
            gateway=mock_gw,
            asset_type="equity",
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "SIMULATED")
        self.assertTrue(result.order_id.startswith("dry-run-order-"))
        self.assertEqual(result.symbol, "SPY")
        self.assertEqual(result.quantity, 1)

        # Verificar auditoría en JSONL
        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_SIMULATED")
        self.assertEqual(history[0].ticker, "SPY")

    def test_quick_trade_success_live_paper(self):
        """TC-MAIN-QT-02: --quick-trade en modo real (paper) envía orden a AlpacaGateway."""
        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = self.mock_snapshot
        mock_gw.get_clock.return_value = self.mock_clock
        mock_gw.submit_stock_order.return_value = {
            "id": "order-paper-live-12345",
            "client_order_id": "client-live-12345",
            "symbol": "SPY",
            "qty": "1",
            "status": "filled",
            "filled_avg_price": "500.02",
        }

        result = run_quick_trade(
            ticker="SPY",
            dry_run=False,
            logger=self.logger,
            gateway=mock_gw,
            asset_type="equity",
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "order-paper-live-12345")
        self.assertEqual(result.status, "FILLED")
        mock_gw.submit_stock_order.assert_called_once()

        history = self.logger.get_trade_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "TRADE_EXECUTED")
        self.assertEqual(history[0].order_id, "order-paper-live-12345")

    def test_quick_trade_rejected_on_frozen_account(self):
        """TC-MAIN-QT-03: Si la cuenta está congelada, RiskEngine rechaza y no se envían órdenes."""
        frozen_snapshot = AccountSnapshot(
            account_id="acc-frozen-999",
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
            is_frozen=True,  # CONGELADA
        )

        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = frozen_snapshot
        mock_gw.get_clock.return_value = self.mock_clock

        result = run_quick_trade(
            ticker="SPY",
            dry_run=False,
            logger=self.logger,
            gateway=mock_gw,
        )

        self.assertIsNone(result)
        mock_gw.submit_stock_order.assert_not_called()
        mock_gw.submit_option_order.assert_not_called()


class TestScalpModeCycle(unittest.TestCase):
    """Verifica el funcionamiento de --mode scalp, timeframe rápido y fallback a acciones."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "scalp_trades.jsonl"
        self.logger = TradeLogger(log_file_path=self.log_file)

        self.mock_snapshot = AccountSnapshot(
            account_id="acc-scalp-001",
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

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scalp_cycle_fallback_to_equity_when_market_closed(self):
        """TC-MAIN-SCALP-01: Cuando el mercado de opciones está cerrado, opera acciones en fallback."""
        closed_clock = MarketClockInfo(
            is_open=False,
            next_open="2026-09-04T09:30:00-04:00",
            next_close="2026-09-04T16:00:00-04:00",
            timestamp="2026-09-03T20:00:00-04:00",
        )

        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = self.mock_snapshot
        mock_gw.get_clock.return_value = closed_clock

        results = run_scalp_cycle(
            universe=["SPY"],
            dry_run=True,
            timeframe="1Min",
            asset_type="auto",
            logger=self.logger,
            gateway=mock_gw,
            max_trades=1,
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].symbol, "SPY")
        self.assertEqual(results[0].quantity, 1)
        self.assertEqual(results[0].status, "SIMULATED")

        # Cero consultas a cadena de opciones ya que el mercado está cerrado
        mock_gw.get_option_chain.assert_not_called()

    def test_scalp_cycle_executes_stock_order_live(self):
        """TC-MAIN-SCALP-02: Modo scalp en paper trading emite orden vía submit_stock_order."""
        closed_clock = MarketClockInfo(
            is_open=False,
            next_open="2026-09-04T09:30:00-04:00",
            next_close="2026-09-04T16:00:00-04:00",
            timestamp="2026-09-03T20:00:00-04:00",
        )

        mock_gw = MagicMock(spec=AlpacaGateway)
        mock_gw.get_account.return_value = self.mock_snapshot
        mock_gw.get_clock.return_value = closed_clock
        mock_gw.submit_stock_order.return_value = {
            "id": "scalp-live-order-777",
            "client_order_id": "client-scalp-777",
            "symbol": "AAPL",
            "qty": "1",
            "status": "filled",
            "filled_avg_price": "180.02",
        }

        results = run_scalp_cycle(
            universe=["AAPL"],
            dry_run=False,
            timeframe="5Min",
            asset_type="equity",
            logger=self.logger,
            gateway=mock_gw,
            max_trades=1,
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].order_id, "scalp-live-order-777")
        self.assertEqual(results[0].status, "FILLED")
        mock_gw.submit_stock_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
