"""
Pruebas Unitarias para Feature 1: Account Management & 5% Risk Limits (FT-ACC-01).
"""

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.account import (
    AccountAuthError,
    AccountConnectionError,
    AccountHealth,
    AccountLimits,
    AccountSnapshot,
    calculate_trade_limits,
    check_account_health,
    get_account_snapshot,
    get_trading_client,
    validate_trade_cost,
)


class TestAccountSnapshot(unittest.TestCase):
    """Pruebas de creación y serialización de AccountSnapshot."""

    def setUp(self):
        self.mock_alpaca_account = SimpleNamespace(
            account_id="acc-123456",
            cash="25000.50",
            portfolio_value="100000.00",
            buying_power="50000.00",
            equity="100000.00",
            long_market_value="75000.00",
            short_market_value="0.00",
            initial_margin="0.00",
            maintenance_margin="0.00",
            daytrading_buying_power="100000.00",
            daytrading_count=1,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
            status="ACTIVE",
        )

    def test_account_snapshot_creation_from_alpaca(self):
        snapshot = AccountSnapshot.from_alpaca_account(self.mock_alpaca_account)
        self.assertEqual(snapshot.account_id, "acc-123456")
        self.assertEqual(snapshot.cash, Decimal("25000.50"))
        self.assertEqual(snapshot.portfolio_value, Decimal("100000.00"))
        self.assertEqual(snapshot.buying_power, Decimal("50000.00"))
        self.assertEqual(snapshot.equity, Decimal("100000.00"))
        self.assertEqual(snapshot.daytrading_count, 1)
        self.assertFalse(snapshot.is_daytrader)
        self.assertTrue(snapshot.is_active)
        self.assertFalse(snapshot.is_frozen)

    def test_account_snapshot_handles_none_and_missing_attributes(self):
        minimal_account = SimpleNamespace(id="min-999")
        snapshot = AccountSnapshot.from_alpaca_account(minimal_account)
        self.assertEqual(snapshot.account_id, "min-999")
        self.assertEqual(snapshot.cash, Decimal("0.0"))
        self.assertEqual(snapshot.portfolio_value, Decimal("0.0"))
        self.assertEqual(snapshot.buying_power, Decimal("0.0"))
        self.assertFalse(snapshot.is_frozen)

    def test_to_dict_serialization(self):
        snapshot = AccountSnapshot.from_alpaca_account(self.mock_alpaca_account)
        data = snapshot.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["account_id"], "acc-123456")
        self.assertEqual(data["portfolio_value"], "100000.00")
        self.assertEqual(data["cash"], "25000.50")


class TestCalculateTradeLimits(unittest.TestCase):
    """Pruebas del motor de cálculo de límites y regla del 5%."""

    def _create_snapshot(self, portfolio_val="100000.00", cash="25000.00", buying_power="50000.00"):
        return AccountSnapshot(
            account_id="test",
            cash=Decimal(cash),
            portfolio_value=Decimal(portfolio_val),
            buying_power=Decimal(buying_power),
            equity=Decimal(portfolio_val),
            long_market_value=Decimal("0.0"),
            short_market_value=Decimal("0.0"),
            initial_margin=Decimal("0.0"),
            maintenance_margin=Decimal("0.0"),
            daytrading_buying_power=Decimal("0.0"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

    def test_calculate_trade_limits_standard_5_percent(self):
        snapshot = self._create_snapshot(portfolio_val="100000.00", cash="25000.00", buying_power="50000.00")
        limits = calculate_trade_limits(snapshot)

        # 5% de $100,000 = $5,000.00
        self.assertEqual(limits.max_single_trade_risk, Decimal("5000.00"))
        # 25% de $100,000 = $25,000.00
        self.assertEqual(limits.max_total_options_allocation, Decimal("25000.00"))
        # Presupuesto efectivo = min(5000, 50000, 25000) = 5000
        self.assertEqual(limits.effective_trade_budget, Decimal("5000.00"))

    def test_effective_trade_budget_constrained_by_low_cash(self):
        snapshot = self._create_snapshot(portfolio_val="100000.00", cash="2000.00", buying_power="2000.00")
        limits = calculate_trade_limits(snapshot)

        self.assertEqual(limits.max_single_trade_risk, Decimal("5000.00"))
        self.assertEqual(limits.effective_trade_budget, Decimal("2000.00"))

    def test_custom_risk_percentage(self):
        snapshot = self._create_snapshot(portfolio_val="200000.00")
        limits = calculate_trade_limits(snapshot, max_risk_pct=Decimal("0.02"))  # 2%
        self.assertEqual(limits.max_single_trade_risk, Decimal("4000.00"))

    def test_invalid_risk_percentage_raises_error(self):
        snapshot = self._create_snapshot()
        with self.assertRaises(ValueError):
            calculate_trade_limits(snapshot, max_risk_pct=Decimal("0.0"))
        with self.assertRaises(ValueError):
            calculate_trade_limits(snapshot, max_risk_pct=Decimal("1.5"))


class TestAccountHealthChecks(unittest.TestCase):
    """Pruebas del guardrail de salud de cuenta y restricciones."""

    def _base_snapshot(self, **kwargs):
        defaults = {
            "account_id": "test-health",
            "cash": Decimal("10000.00"),
            "portfolio_value": Decimal("50000.00"),
            "buying_power": Decimal("20000.00"),
            "equity": Decimal("50000.00"),
            "long_market_value": Decimal("40000.00"),
            "short_market_value": Decimal("0.00"),
            "initial_margin": Decimal("0.00"),
            "maintenance_margin": Decimal("5000.00"),
            "daytrading_buying_power": Decimal("50000.00"),
            "daytrading_count": 0,
            "is_daytrader": False,
            "is_active": True,
            "is_frozen": False,
        }
        defaults.update(kwargs)
        return AccountSnapshot(**defaults)

    def test_healthy_account(self):
        snapshot = self._base_snapshot()
        health = check_account_health(snapshot)
        self.assertTrue(health.is_healthy)
        self.assertTrue(health.can_trade)
        self.assertEqual(len(health.critical_errors), 0)
        self.assertEqual(len(health.warnings), 0)

    def test_frozen_account_blocks_trading(self):
        snapshot = self._base_snapshot(is_frozen=True)
        health = check_account_health(snapshot)
        self.assertFalse(health.can_trade)
        self.assertFalse(health.is_healthy)
        self.assertTrue(any("CONGELADA" in err for err in health.critical_errors))

    def test_inactive_account_blocks_trading(self):
        snapshot = self._base_snapshot(is_active=False)
        health = check_account_health(snapshot)
        self.assertFalse(health.can_trade)
        self.assertTrue(any("NO está activa" in err for err in health.critical_errors))

    def test_margin_call_danger_blocks_trading(self):
        snapshot = self._base_snapshot(equity=Decimal("10000.00"), maintenance_margin=Decimal("11000.00"))
        health = check_account_health(snapshot)
        self.assertFalse(health.can_trade)
        self.assertTrue(any("Margin Call" in err for err in health.critical_errors))

    def test_pdt_warning_when_daytrading_count_high(self):
        snapshot = self._base_snapshot(daytrading_count=3, is_daytrader=False)
        health = check_account_health(snapshot)
        self.assertTrue(health.can_trade)
        self.assertFalse(health.is_healthy)
        self.assertTrue(any("PDT" in warn for warn in health.warnings))


class TestValidateTradeCost(unittest.TestCase):
    """Pruebas del validador de costo de trade vs límites calculados."""

    def setUp(self):
        self.limits = AccountLimits(
            portfolio_value=Decimal("100000.00"),
            buying_power=Decimal("20000.00"),
            max_risk_pct=Decimal("0.05"),
            max_single_trade_risk=Decimal("5000.00"),
            max_portfolio_risk_pct=Decimal("0.25"),
            max_total_options_allocation=Decimal("25000.00"),
            effective_trade_budget=Decimal("5000.00"),
        )

    def test_trade_cost_within_limit_approved(self):
        approved, msg = validate_trade_cost(Decimal("1500.00"), self.limits)
        self.assertTrue(approved)
        self.assertIn("aprobado", msg.lower())

    def test_trade_cost_exact_limit_approved(self):
        approved, msg = validate_trade_cost(Decimal("5000.00"), self.limits)
        self.assertTrue(approved)

    def test_trade_cost_exceeding_limit_rejected(self):
        approved, msg = validate_trade_cost(Decimal("5000.01"), self.limits)
        self.assertFalse(approved)
        self.assertIn("excede el límite", msg.lower())

    def test_trade_cost_zero_rejected(self):
        approved, msg = validate_trade_cost(Decimal("0.00"), self.limits)
        self.assertFalse(approved)


class TestClientAndIntegration(unittest.TestCase):
    """Pruebas de inicialización y manejo de errores de cliente."""

    @patch.dict("os.environ", {}, clear=True)
    def test_get_trading_client_missing_keys_raises_auth_error(self):
        with self.assertRaises(AccountAuthError):
            get_trading_client()

    def test_get_account_snapshot_with_mock_client(self):
        mock_client = MagicMock()
        mock_client.get_account.return_value = SimpleNamespace(
            account_id="mock-id",
            cash="12000",
            portfolio_value="50000",
            buying_power="25000",
            equity="50000",
            long_market_value="38000",
            short_market_value="0",
            initial_margin="0",
            maintenance_margin="0",
            daytrading_buying_power="50000",
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
            status="ACTIVE",
        )

        snapshot = get_account_snapshot(mock_client)
        self.assertEqual(snapshot.account_id, "mock-id")
        self.assertEqual(snapshot.portfolio_value, Decimal("50000"))

    def test_get_account_snapshot_connection_error(self):
        mock_client = MagicMock()
        mock_client.get_account.side_effect = RuntimeError("Network timeout")

        with self.assertRaises(AccountConnectionError):
            get_account_snapshot(mock_client)


if __name__ == "__main__":
    unittest.main()

