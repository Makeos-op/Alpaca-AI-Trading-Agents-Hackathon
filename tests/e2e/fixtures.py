"""
Fixtures, Factories, and Contract Mocks for the Opaque-Box E2E Test Suite.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from src.account import AccountSnapshot
from src.indicators.technicals import to_decimal
from src.options.models import OptionContract, OptionGreeks, OptionType
from src.risk.risk_engine import RiskEngine, RiskVerdict, TradeProposal


# ==========================================
# Reason Code Definitions per PROJECT.md & spec_report.md
# ==========================================

class RiskReasonCodeContract(str, Enum):
    """Authoritative Reason Codes from PROJECT.md and spec_report.md."""
    APPROVED = "APPROVED"
    ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT = "ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT"
    ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP = "ERR_EXCEEDS_PORTFOLIO_OPTIONS_CAP"
    ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT = "ERR_EXCEEDS_25PCT_CUMULATIVE_OPTIONS_LIMIT"
    ERR_INSUFFICIENT_BUYING_POWER = "ERR_INSUFFICIENT_BUYING_POWER"
    ERR_INSUFFICIENT_CASH = "ERR_INSUFFICIENT_CASH"
    ERR_ACCOUNT_FROZEN_OR_RESTRICTED = "ERR_ACCOUNT_FROZEN_OR_RESTRICTED"
    ERR_ACCOUNT_FROZEN = "ERR_ACCOUNT_FROZEN"
    ERR_ACCOUNT_INACTIVE = "ERR_ACCOUNT_INACTIVE"
    ERR_MARGIN_CALL_RISK = "ERR_MARGIN_CALL_RISK"
    ERR_ZERO_PORTFOLIO_VALUE = "ERR_ZERO_PORTFOLIO_VALUE"
    ERR_WIDE_BID_ASK_SPREAD = "ERR_WIDE_BID_ASK_SPREAD"
    ERR_SPREAD_EXCEEDS_MAX = "ERR_SPREAD_EXCEEDS_MAX"
    ERR_CROSSED_OR_ZERO_QUOTE = "ERR_CROSSED_OR_ZERO_QUOTE"
    ERR_SPREAD_INVALID_OR_CROSSED = "ERR_SPREAD_INVALID_OR_CROSSED"
    ERR_INSUFFICIENT_OPEN_INTEREST = "ERR_INSUFFICIENT_OPEN_INTEREST"
    ERR_OPEN_INTEREST_BELOW_MIN = "ERR_OPEN_INTEREST_BELOW_MIN"
    ERR_INSUFFICIENT_VOLUME = "ERR_INSUFFICIENT_VOLUME"
    ERR_VOLUME_BELOW_MIN = "ERR_VOLUME_BELOW_MIN"
    ERR_DTE_OUT_OF_BOUNDS = "ERR_DTE_OUT_OF_BOUNDS"
    ERR_DTE_BELOW_MIN = "ERR_DTE_BELOW_MIN"
    ERR_DTE_ABOVE_MAX = "ERR_DTE_ABOVE_MAX"
    ERR_DELTA_OUT_OF_BOUNDS = "ERR_DELTA_OUT_OF_BOUNDS"
    ERR_THETA_DECAY_EXCESSIVE = "ERR_THETA_DECAY_EXCESSIVE"
    ERR_IV_OUT_OF_BOUNDS = "ERR_IV_OUT_OF_BOUNDS"
    ERR_IV_OUT_OF_RANGE = "ERR_IV_OUT_OF_RANGE"
    ERR_INVALID_ORDER_QUANTITY = "ERR_INVALID_ORDER_QUANTITY"


# ==========================================
# Factories
# ==========================================

class MockAccountSnapshotFactory:
    """Creates realistic AccountSnapshot instances for E2E testing."""

    @staticmethod
    def create_healthy_account(
        portfolio_value: Decimal = Decimal("100000.00"),
        cash: Decimal = Decimal("50000.00"),
        buying_power: Decimal = Decimal("100000.00"),
        account_id: str = "acc-e2e-healthy",
    ) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=account_id,
            cash=cash,
            portfolio_value=portfolio_value,
            buying_power=buying_power,
            equity=portfolio_value,
            long_market_value=portfolio_value - cash,
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=buying_power,
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

    @staticmethod
    def create_low_cash_account(
        portfolio_value: Decimal = Decimal("100000.00"),
        cash: Decimal = Decimal("600.00"),
        buying_power: Decimal = Decimal("50000.00"),
    ) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="acc-e2e-low-cash",
            cash=cash,
            portfolio_value=portfolio_value,
            buying_power=buying_power,
            equity=portfolio_value,
            long_market_value=portfolio_value - cash,
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=buying_power,
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=False,
        )

    @staticmethod
    def create_frozen_account() -> AccountSnapshot:
        return AccountSnapshot(
            account_id="acc-e2e-frozen",
            cash=Decimal("10000.00"),
            portfolio_value=Decimal("50000.00"),
            buying_power=Decimal("0.00"),
            equity=Decimal("50000.00"),
            long_market_value=Decimal("40000.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=True,
            is_frozen=True,
        )

    @staticmethod
    def create_margin_call_account() -> AccountSnapshot:
        return AccountSnapshot(
            account_id="acc-e2e-margin-call",
            cash=Decimal("500.00"),
            portfolio_value=Decimal("50000.00"),
            buying_power=Decimal("0.00"),
            equity=Decimal("50000.00"),
            long_market_value=Decimal("49500.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("40000.00"),
            maintenance_margin=Decimal("55000.00"),  # > equity
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=4,
            is_daytrader=True,
            is_active=True,
            is_frozen=False,
        )

    @staticmethod
    def create_zero_equity_account() -> AccountSnapshot:
        return AccountSnapshot(
            account_id="acc-e2e-zero-equity",
            cash=Decimal("0.00"),
            portfolio_value=Decimal("0.00"),
            buying_power=Decimal("0.00"),
            equity=Decimal("0.00"),
            long_market_value=Decimal("0.00"),
            short_market_value=Decimal("0.00"),
            initial_margin=Decimal("0.00"),
            maintenance_margin=Decimal("0.00"),
            daytrading_buying_power=Decimal("0.00"),
            daytrading_count=0,
            is_daytrader=False,
            is_active=False,
            is_frozen=False,
        )


class MockOptionContractFactory:
    """Creates realistic OptionContract instances for E2E testing."""

    @staticmethod
    def create_valid_contract(
        symbol: str = "SPY260930C00500000",
        underlying_symbol: str = "SPY",
        contract_type: OptionType = OptionType.CALL,
        strike_price: str = "500.00",
        bid_price: Optional[str] = None,
        ask_price: str = "2.20",
        dte: int = 20,
        volume: int = 1500,
        open_interest: int = 2500,
        delta: str = "0.50",
        theta: str = "-0.04",
        implied_volatility: str = "0.1850",
    ) -> OptionContract:
        if bid_price is None:
            if ask_price == "2.20":
                # Comportamiento histórico por defecto (spread de referencia $0.10).
                bid_price = "2.10"
            else:
                # Deriva un bid ~2% por debajo del ask (spread pequeño y válido)
                # cuando solo se sobreescribe ask_price, evitando spreads
                # artificialmente anchos o cotizaciones cruzadas (ask <= bid).
                ask_dec = Decimal(str(ask_price))
                bid_price = str((ask_dec * Decimal("0.98")).quantize(Decimal("0.01")))
        return OptionContract.create(
            symbol=symbol,
            underlying_symbol=underlying_symbol,
            contract_type=contract_type,
            strike_price=strike_price,
            expiration_date="2026-09-30",
            dte=dte,
            bid_price=bid_price,
            ask_price=ask_price,
            volume=volume,
            open_interest=open_interest,
            delta=delta,
            gamma="0.08",
            theta=theta,
            vega="0.12",
            implied_volatility=implied_volatility,
        )

    @staticmethod
    def create_wide_spread_contract(
        bid: str = "1.00",
        ask: str = "1.50",  # spread = 0.50 / 1.25 = 40%
    ) -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price=bid,
            ask_price=ask,
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.03",
        )

    @staticmethod
    def create_crossed_quote_contract() -> OptionContract:
        # Ask < Bid (Crossed market)
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.50",
            ask_price="2.40",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.03",
        )

    @staticmethod
    def create_zero_bid_contract() -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="0.00",
            ask_price="1.50",
            volume=1000,
            open_interest=2000,
            delta="0.50",
            theta="-0.03",
        )

    @staticmethod
    def create_zero_dte_contract() -> OptionContract:
        return OptionContract.create(
            symbol="SPY260903C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-03",
            dte=0,
            bid_price="2.10",
            ask_price="2.20",
            volume=2000,
            open_interest=3000,
            delta="0.50",
            theta="-0.05",
        )

    @staticmethod
    def create_far_dte_contract() -> OptionContract:
        return OptionContract.create(
            symbol="SPY261231C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-12-31",
            dte=60,
            bid_price="5.10",
            ask_price="5.25",
            volume=800,
            open_interest=1500,
            delta="0.50",
            theta="-0.01",
        )

    @staticmethod
    def create_low_oi_contract(oi: int = 150) -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.10",
            ask_price="2.20",
            volume=1000,
            open_interest=oi,
            delta="0.50",
            theta="-0.03",
            implied_volatility="0.20",
        )

    @staticmethod
    def create_low_volume_contract(vol: int = 20) -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.10",
            ask_price="2.20",
            volume=vol,
            open_interest=1200,
            delta="0.50",
            theta="-0.03",
        )

    @staticmethod
    def create_deep_otm_call(delta: str = "0.12") -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930C00550000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="550.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="0.40",
            ask_price="0.42",
            volume=500,
            open_interest=1000,
            delta=delta,
            theta="-0.02",
        )

    @staticmethod
    def create_deep_itm_put(delta: str = "-0.85") -> OptionContract:
        return OptionContract.create(
            symbol="SPY260930P00550000",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="550.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="52.00",
            ask_price="52.50",
            volume=300,
            open_interest=800,
            delta=delta,
            theta="-0.02",
        )

    @staticmethod
    def create_excessive_theta_contract(ask: str = "0.40", theta: str = "-0.05") -> OptionContract:
        # |theta| / ask = 0.05 / 0.40 = 12.5% daily decay (> 5%)
        return OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="0.38",
            ask_price=ask,
            volume=500,
            open_interest=1000,
            delta="0.45",
            theta=theta,
        )


# ==========================================
# Draft-07 JSON Schema Validator for Audit Log
# ==========================================

class Draft07SchemaValidator:
    """
    Validates log records against the Draft-07 schema defined in spec_report.md § 2.1.
    Performs deterministic field presence, type checking, and regex validations.
    """

    REQUIRED_TOP_LEVEL = [
        "timestamp",
        "event_type",
        "mode",
        "market_data_snapshot",
        "agent_proposal",
        "risk_verdict",
        "execution_result",
    ]

    REQUIRED_MARKET_DATA = [
        "ticker",
        "underlying_price",
        "bid_price",
        "ask_price",
        "mid_price",
        "spread_pct",
        "volume",
        "open_interest",
        "greeks",
    ]

    REQUIRED_PROPOSAL = [
        "strategy_name",
        "signal_type",
        "confidence",
        "target_option_type",
        "action",
        "quantity",
    ]

    REQUIRED_VERDICT = [
        "is_approved",
        "trade_cost",
        "max_allowed_budget",
        "portfolio_risk_pct_used",
        "reasons",
        "reason_codes",
    ]

    REQUIRED_EXECUTION = [
        "executed",
        "execution_status",
    ]

    ISO8601_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    @classmethod
    def validate(cls, record: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validates a log entry dictionary against the schema.
        Returns (is_valid, list_of_errors).
        """
        errors: list[str] = []

        # Check top-level required fields
        for req in cls.REQUIRED_TOP_LEVEL:
            if req not in record:
                errors.append(f"Missing required top-level field: '{req}'")

        if errors:
            return False, errors

        # Validate timestamp
        ts = record.get("timestamp", "")
        if not isinstance(ts, str) or not cls.ISO8601_REGEX.match(ts):
            errors.append(f"Invalid timestamp format: '{ts}' (must be ISO-8601 string)")

        # Validate event_type
        event_type = record.get("event_type")
        if event_type not in ["TRADE_EXECUTED", "TRADE_REJECTED", "TRADE_SIMULATED"]:
            errors.append(f"Invalid event_type: '{event_type}'")

        # Validate mode
        mode = record.get("mode")
        if mode not in ["dry-run", "scan", "loop", "scalp"]:
            errors.append(f"Invalid mode: '{mode}'")

        # Validate market_data_snapshot
        snap = record.get("market_data_snapshot")
        if not isinstance(snap, dict):
            errors.append("market_data_snapshot must be an object")
        else:
            for req in cls.REQUIRED_MARKET_DATA:
                if req not in snap:
                    errors.append(f"market_data_snapshot missing '{req}'")

        # Validate agent_proposal
        proposal = record.get("agent_proposal")
        if not isinstance(proposal, dict):
            errors.append("agent_proposal must be an object")
        else:
            for req in cls.REQUIRED_PROPOSAL:
                if req not in proposal:
                    errors.append(f"agent_proposal missing '{req}'")
            if proposal.get("quantity", 0) < 1:
                errors.append("agent_proposal.quantity must be >= 1")

        # Validate risk_verdict
        verdict = record.get("risk_verdict")
        if not isinstance(verdict, dict):
            errors.append("risk_verdict must be an object")
        else:
            for req in cls.REQUIRED_VERDICT:
                if req not in verdict:
                    errors.append(f"risk_verdict missing '{req}'")
            if not isinstance(verdict.get("is_approved"), bool):
                errors.append("risk_verdict.is_approved must be a boolean")
            if not isinstance(verdict.get("reasons"), list):
                errors.append("risk_verdict.reasons must be an array")
            if not isinstance(verdict.get("reason_codes"), list):
                errors.append("risk_verdict.reason_codes must be an array")

        # Validate execution_result
        exec_res = record.get("execution_result")
        if not isinstance(exec_res, dict):
            errors.append("execution_result must be an object")
        else:
            for req in cls.REQUIRED_EXECUTION:
                if req not in exec_res:
                    errors.append(f"execution_result missing '{req}'")
            status = exec_res.get("execution_status")
            if status not in ["FILLED", "NEW", "REJECTED", "SIMULATED", "ERROR"]:
                errors.append(f"Invalid execution_status: '{status}'")

        return len(errors) == 0, errors


# ==========================================
# Mock Protocol Simulators (MCP Stdio & CLI)
# ==========================================

class MockMCPStdioProtocolSimulator:
    """Simulates stdio JSON-RPC protocol exchange with the official alpaca-mcp-server."""

    def __init__(self, fail_on_order: bool = False, disconnect_on_query: bool = False):
        self.fail_on_order = fail_on_order
        self.disconnect_on_query = disconnect_on_query
        self.query_count = 0
        self.is_connected = True

    def handle_request(self, request_json_str: str) -> str:
        """Processes an incoming JSON-RPC request string and returns the JSON-RPC response."""
        if not self.is_connected:
            raise BrokenPipeError("MCP stdio process pipe broken")

        self.query_count += 1
        if self.disconnect_on_query and self.query_count >= 1:
            self.is_connected = False
            raise ConnectionResetError("MCP server terminated unexpectedly")

        try:
            req = json.loads(request_json_str)
        except json.JSONDecodeError as exc:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            })

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "tools/list":
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {"name": "get_account", "description": "Get Alpaca account snapshot"},
                        {"name": "get_clock", "description": "Get market clock"},
                        {"name": "get_calendar", "description": "Get market calendar"},
                        {"name": "get_option_chain", "description": "Get options chain"},
                        {"name": "submit_option_order", "description": "Submit option order"},
                        {"name": "place_stock_order", "description": "Place stock or ETF order"},
                        {"name": "place_option_order", "description": "Place option contract order"},
                    ]
                },
            })

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "get_account":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "account_id": "acc-mcp-mock-123",
                        "portfolio_value": "100000.00",
                        "cash": "50000.00",
                        "buying_power": "100000.00",
                        "equity": "100000.00",
                        "status": "ACTIVE",
                    },
                })

            elif tool_name == "get_clock":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "timestamp": "2026-09-03T14:30:00Z",
                        "is_open": True,
                        "next_open": "2026-09-04T13:30:00Z",
                        "next_close": "2026-09-03T20:00:00Z",
                    },
                })

            elif tool_name == "get_calendar":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": [
                        {"date": "2026-09-03", "open": "09:30", "close": "16:00", "session_open": "0400", "session_close": "2000"}
                    ],
                })

            elif tool_name == "get_option_chain":
                underlying = args.get("underlying", "SPY")
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contracts": [
                            {
                                "symbol": f"{underlying}260930C00500000",
                                "underlying_symbol": underlying,
                                "type": "call",
                                "strike": "500.00",
                                "expiration": "2026-09-30",
                                "dte": 20,
                                "bid": "2.10",
                                "ask": "2.20",
                                "volume": 1500,
                                "open_interest": 2500,
                                "delta": "0.50",
                                "theta": "-0.04",
                            }
                        ]
                    },
                })

            elif tool_name in ["submit_option_order", "place_option_order", "place_stock_order"]:
                if self.fail_on_order:
                    return json.dumps({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": "Broker rejected order: Insufficient buying power"},
                    })
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "order_id": "mcp-order-98765",
                        "symbol": args.get("symbol"),
                        "qty": args.get("qty"),
                        "side": args.get("side"),
                        "status": "FILLED",
                        "fill_price": "2.20",
                    },
                })

        return json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


class MockCLIRunnerSimulator:
    """Simulates invocation of `/usr/bin/alpaca` CLI tool and JSON output parsing."""

    @staticmethod
    def run_command(args: list[str]) -> tuple[int, str, str]:
        """
        Simulates running `/usr/bin/alpaca <args>`.
        Returns (exit_code, stdout, stderr).
        """
        if not args:
            return 1, "", "Error: no subcommand provided"

        subcmd = args[0]
        if subcmd == "account":
            if "--json" in args or "get" in args:
                return 0, json.dumps({
                    "id": "acc-cli-12345",
                    "portfolio_value": "100000.00",
                    "cash": "50000.00",
                    "buying_power": "100000.00",
                    "equity": "100000.00",
                    "status": "ACTIVE",
                }), ""
            return 0, "Account ID: acc-cli-12345\nPortfolio: $100,000.00", ""

        elif subcmd == "clock":
            if "--json" in args:
                return 0, json.dumps({
                    "timestamp": "2026-09-03T14:30:00Z",
                    "is_open": True,
                    "next_open": "2026-09-04T13:30:00Z",
                    "next_close": "2026-09-03T20:00:00Z",
                }), ""
            return 0, "Market is OPEN", ""

        elif subcmd == "profile":
            if "login" in args:
                return 0, "Profile default logged in successfully", ""
            return 0, "default", ""

        elif subcmd == "order":
            if "place" in args or "submit" in args:
                sym = "SPY260930C00500000"
                qty = 5
                for i, a in enumerate(args):
                    if a == "--symbol" and i + 1 < len(args):
                        sym = args[i + 1]
                    elif a == "--qty" and i + 1 < len(args):
                        try:
                            qty = int(args[i + 1])
                        except ValueError:
                            qty = 1
                return 0, json.dumps({
                    "id": "cli-order-abcdef",
                    "status": "accepted",
                    "symbol": sym,
                    "qty": qty,
                }), ""

        return 1, "", f"Unknown CLI command: {' '.join(args)}"
