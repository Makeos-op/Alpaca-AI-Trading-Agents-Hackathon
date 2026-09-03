"""
Pytest configuration and fixtures for E2E test suite.
"""

import pytest
from decimal import Decimal

from tests.e2e.fixtures import (
    MockAccountSnapshotFactory,
    MockOptionContractFactory,
    MockMCPStdioProtocolSimulator,
    MockCLIRunnerSimulator,
    Draft07SchemaValidator,
)
from src.risk.risk_engine import RiskEngine


@pytest.fixture
def risk_engine() -> RiskEngine:
    """Provides standard RiskEngine with 5% single-trade and 25% portfolio options cap."""
    return RiskEngine(
        max_risk_pct=Decimal("0.05"),
        max_portfolio_options_pct=Decimal("0.25"),
    )


@pytest.fixture
def healthy_account():
    """Provides a standard $100,000 equity healthy AccountSnapshot."""
    return MockAccountSnapshotFactory.create_healthy_account()


@pytest.fixture
def valid_call_contract():
    """Provides a standard valid ATM SPY Call contract."""
    return MockOptionContractFactory.create_valid_contract()


@pytest.fixture
def mcp_simulator():
    """Provides a fresh MockMCPStdioProtocolSimulator instance."""
    return MockMCPStdioProtocolSimulator()


@pytest.fixture
def schema_validator():
    """Provides the Draft-07 schema validator."""
    return Draft07SchemaValidator
