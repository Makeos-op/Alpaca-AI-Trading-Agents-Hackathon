"""
tests/test_mcp_gateway.py

Comprehensive unit test suite for Alpaca MCP and CLI Gateway (Milestone 1: F1.1 - F1.5).
Covers:
- Tool discovery across transports (Mock, CLI, Stdio)
- Alpaca CLI subprocess invocation and JSON parsing
- Offline MockMCPTransport state, option chain generation, and order simulation
- AlpacaGateway unified Interface Contract (get_account, get_clock, get_option_chain, submit_option_order)
- Resilience, reconnection, and error recovery
- OCC / OSI option symbology encoding and decoding
- Seamless integration with src/account.py
"""

import json
import subprocess
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.account import AccountSnapshot, MarketClock, MarketClockInfo, get_account_snapshot, get_market_clock
from src.execution.mcp_gateway import (
    AlpacaGateway,
    BaseAlpacaTransport,
    CLIExecutionError,
    CLITransport,
    GatewayError,
    GatewayInitializationError,
    MCPConnectionClosedError,
    MCPTool,
    MCPTransportError,
    MockMCPTransport,
    OptionOrderError,
    StdioMCPTransport,
    build_occ_symbol,
    parse_occ_symbol,
)
from src.options.models import OptionContract, OptionType


class TestOCCSymbology(unittest.TestCase):
    """Pruebas de codificación y decodificación de simbología estándar OCC / OSI."""

    def test_parse_valid_call_symbol(self):
        info = parse_occ_symbol("SPY260930C00500000")
        self.assertEqual(info["underlying"], "SPY")
        self.assertEqual(info["expiration_date"], "2026-09-30")
        self.assertEqual(info["contract_type"], OptionType.CALL)
        self.assertEqual(info["strike_price"], Decimal("500.00"))

    def test_parse_valid_put_symbol(self):
        info = parse_occ_symbol("AAPL261015P00225500")
        self.assertEqual(info["underlying"], "AAPL")
        self.assertEqual(info["expiration_date"], "2026-10-15")
        self.assertEqual(info["contract_type"], OptionType.PUT)
        self.assertEqual(info["strike_price"], Decimal("225.50"))

    def test_parse_invalid_symbol_raises_error(self):
        with self.assertRaises(ValueError):
            parse_occ_symbol("INVALID_SYM")

        with self.assertRaises(ValueError):
            parse_occ_symbol("SPY260930X00500000")  # 'X' no es 'C' ni 'P'

    def test_build_occ_symbol_roundtrip(self):
        sym = build_occ_symbol(
            underlying="SPY",
            expiration_date="2026-09-30",
            contract_type=OptionType.CALL,
            strike_price=Decimal("500.00"),
        )
        self.assertEqual(sym, "SPY260930C00500000")
        parsed = parse_occ_symbol(sym)
        self.assertEqual(parsed["underlying"], "SPY")
        self.assertEqual(parsed["strike_price"], Decimal("500.00"))


class TestToolDiscovery(unittest.TestCase):
    """Pruebas de descubrimiento de herramientas (Tool Discovery) en el protocolo MCP."""

    def test_mock_transport_tool_discovery(self):
        mock_transport = MockMCPTransport()
        mock_transport.initialize()
        tools = mock_transport.list_tools()

        tool_names = [t.name for t in tools]
        expected_tools = [
            "get_account",
            "get_clock",
            "get_all_positions",
            "get_option_contracts",
            "get_option_snapshots",
            "post_order",
        ]
        for exp in expected_tools:
            self.assertIn(exp, tool_names)

        # Validar que cada herramienta contiene esquema y descripción
        for tool in tools:
            self.assertIsInstance(tool, MCPTool)
            self.assertTrue(len(tool.description) > 0)
            self.assertIsInstance(tool.input_schema, dict)

    def test_cli_transport_tool_discovery(self):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        tools = cli.list_tools()
        names = [t.name for t in tools]
        self.assertIn("alpaca_account_get", names)
        self.assertIn("alpaca_order_submit", names)

    def test_gateway_exposes_tool_discovery(self):
        gateway = AlpacaGateway(mode="mock")
        tools = gateway.list_tools()
        self.assertTrue(len(tools) >= 5)
        names = [t.name for t in tools]
        self.assertIn("get_account", names)


class TestCLITransport(unittest.TestCase):
    """Pruebas unitarias de ejecución y parsing del transporte Alpaca CLI (/usr/bin/alpaca)."""

    def test_cli_initialization_fails_when_binary_missing(self):
        cli = CLITransport(binary_path="/nonexistent/path/to/alpaca")
        with self.assertRaises(CLIExecutionError):
            cli.initialize()

    @patch("shutil.which", return_value="/usr/bin/alpaca")
    @patch("subprocess.run")
    def test_cli_get_account_success(self, mock_subproc, mock_which):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        cli.initialize()

        fake_json = {
            "id": "cli-acc-123",
            "cash": "45000.00",
            "portfolio_value": "90000.00",
            "buying_power": "90000.00",
            "status": "ACTIVE",
        }
        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/alpaca", "account", "get", "--format", "json"],
            returncode=0,
            stdout=json.dumps(fake_json),
            stderr="",
        )

        acc = cli.get_account()
        self.assertEqual(acc["id"], "cli-acc-123")
        self.assertEqual(acc["cash"], "45000.00")
        mock_subproc.assert_called()

    @patch("shutil.which", return_value="/usr/bin/alpaca")
    @patch("subprocess.run")
    def test_cli_get_clock_success(self, mock_subproc, mock_which):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        cli.initialize()

        fake_clock = {
            "is_open": True,
            "next_open": "2026-09-04T09:30:00-04:00",
            "next_close": "2026-09-03T16:00:00-04:00",
            "timestamp": "2026-09-03T14:30:00-04:00",
        }
        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/alpaca", "market", "clock", "--format", "json"],
            returncode=0,
            stdout=json.dumps(fake_clock),
            stderr="",
        )

        clock = cli.get_clock()
        self.assertTrue(clock["is_open"])
        self.assertEqual(clock["next_close"], "2026-09-03T16:00:00-04:00")

    @patch("shutil.which", return_value="/usr/bin/alpaca")
    @patch("subprocess.run")
    def test_cli_submit_order_success(self, mock_subproc, mock_which):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        cli.initialize()

        fake_order = {
            "id": "order-cli-999",
            "symbol": "SPY260930C00500000",
            "qty": "3",
            "side": "buy",
            "status": "filled",
            "filled_avg_price": "2.35",
        }
        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/alpaca", "order", "submit", "--format", "json"],
            returncode=0,
            stdout=json.dumps(fake_order),
            stderr="",
        )

        res = cli.submit_order(
            symbol="SPY260930C00500000",
            qty=3,
            side="buy",
            time_in_force="day",
            order_type="limit",
            limit_price=Decimal("2.35"),
            client_order_id="cid-001",
        )
        self.assertEqual(res["id"], "order-cli-999")
        self.assertEqual(res["status"], "filled")

        # Verificar que los argumentos pasados incluyeron --limit-price y --client-order-id
        called_cmd = mock_subproc.call_args[0][0]
        self.assertIn("--limit-price", called_cmd)
        self.assertIn("2.35", called_cmd)
        self.assertIn("--client-order-id", called_cmd)
        self.assertIn("cid-001", called_cmd)

    @patch("shutil.which", return_value="/usr/bin/alpaca")
    @patch("subprocess.run")
    def test_cli_handles_return_code_error(self, mock_subproc, mock_which):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        cli.initialize()

        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/alpaca", "account"],
            returncode=1,
            stdout="",
            stderr="authentication failed: invalid API key",
        )
        with self.assertRaises(CLIExecutionError):
            cli.get_account()

    @patch("shutil.which", return_value="/usr/bin/alpaca")
    @patch("subprocess.run")
    def test_cli_handles_invalid_json(self, mock_subproc, mock_which):
        cli = CLITransport(binary_path="/usr/bin/alpaca")
        cli.initialize()

        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/alpaca", "account"],
            returncode=0,
            stdout="Corrupted non-json output",
            stderr="",
        )
        with self.assertRaises(CLIExecutionError):
            cli.get_account()


class TestMockMCPTransport(unittest.TestCase):
    """Pruebas del transporte offline MockMCPTransport."""

    def setUp(self):
        self.transport = MockMCPTransport(
            portfolio_value=Decimal("150000.00"),
            cash=Decimal("80000.00"),
            buying_power=Decimal("160000.00"),
        )
        self.transport.initialize()

    def test_get_account_state(self):
        acc = self.transport.get_account()
        self.assertEqual(acc["portfolio_value"], "150000.00")
        self.assertEqual(acc["cash"], "80000.00")
        self.assertEqual(acc["buying_power"], "160000.00")
        self.assertEqual(acc["status"], "ACTIVE")
        self.assertFalse(acc["is_frozen"])

    def test_get_clock_state(self):
        clock = self.transport.get_clock()
        self.assertTrue(clock["is_open"])
        self.assertIn("next_open", clock)
        self.assertIn("next_close", clock)

    def test_get_option_contracts_generates_valid_chain(self):
        contracts = self.transport.get_option_contracts("SPY", min_dte=5, max_dte=25)
        self.assertTrue(len(contracts) > 0)

        for c in contracts:
            self.assertEqual(c["underlying_symbol"], "SPY")
            self.assertTrue(5 <= c["dte"] <= 25)
            self.assertIn(c["contract_type"], ["CALL", "PUT"])

            # Validar que los campos numéricos sean parseables
            bid = Decimal(c["bid_price"])
            ask = Decimal(c["ask_price"])
            self.assertTrue(ask >= bid)
            self.assertTrue(bid > Decimal("0.0"))

            # Validar griegas
            greeks = c["greeks"]
            delta = Decimal(greeks["delta"])
            if c["contract_type"] == "CALL":
                self.assertTrue(Decimal("0.0") < delta <= Decimal("1.0"))
            else:
                self.assertTrue(Decimal("-1.0") <= delta < Decimal("0.0"))

    def test_submit_order_stores_and_returns_result(self):
        res = self.transport.submit_order(
            symbol="SPY260930C00500000",
            qty=2,
            side="buy",
            time_in_force="day",
            order_type="market",
        )
        self.assertEqual(res["status"], "filled")
        self.assertEqual(res["qty"], "2")
        self.assertEqual(res["symbol"], "SPY260930C00500000")
        self.assertEqual(len(self.transport.submitted_orders), 1)

    def test_simulate_disconnect_and_reset(self):
        self.transport.simulate_disconnect()
        with self.assertRaises(MCPConnectionClosedError):
            self.transport.get_account()

        # Restablecer
        self.transport.reset_simulation()
        acc = self.transport.get_account()
        self.assertIn("portfolio_value", acc)

    def test_simulate_tool_error(self):
        self.transport.simulate_tool_error("post_order", MCPTransportError("Insufficient liquidity in contract"))
        with self.assertRaises(MCPTransportError):
            self.transport.submit_order(symbol="SPY260930C00500000", qty=1, side="buy")

        self.transport.reset_simulation()
        res = self.transport.submit_order(symbol="SPY260930C00500000", qty=1, side="buy")
        self.assertEqual(res["status"], "filled")

    def test_mock_transport_anchor_date_dynamic_utc_by_default(self):
        """Verifica que sin anchor_date explícito, la fecha ancla sea dinámica en UTC y sin NameError."""
        transport = MockMCPTransport()
        now_utc = datetime.now(timezone.utc).date()
        contracts = transport.get_option_contracts("SPY", min_dte=5, max_dte=15)
        self.assertTrue(len(contracts) > 0)

        for c in contracts:
            dte = c["dte"]
            expected_exp = (now_utc + timedelta(days=dte)).strftime("%Y-%m-%d")
            self.assertEqual(c["expiration_date"], expected_exp)

    def test_mock_transport_anchor_date_explicit_override(self):
        """Verifica que se respete un anchor_date explícito tanto en constructor como en get_option_contracts."""
        fixed_date = date(2027, 4, 15)
        transport = MockMCPTransport(anchor_date=fixed_date)
        contracts = transport.get_option_contracts("AAPL", min_dte=7, max_dte=21)
        self.assertTrue(len(contracts) > 0)

        for c in contracts:
            dte = c["dte"]
            expected_exp = (fixed_date + timedelta(days=dte)).strftime("%Y-%m-%d")
            self.assertEqual(c["expiration_date"], expected_exp)

        # También verificar override temporal vía parámetro filters
        override_date = date(2028, 1, 10)
        contracts_override = transport.get_option_contracts("MSFT", min_dte=10, max_dte=10, anchor_date=override_date)
        self.assertTrue(len(contracts_override) > 0)
        expected_override_exp = (override_date + timedelta(days=10)).strftime("%Y-%m-%d")
        self.assertEqual(contracts_override[0]["expiration_date"], expected_override_exp)

    def test_mock_transport_clock_uses_anchor_date(self):
        """Verifica que get_clock refleje la fecha ancla configurada o dinámica."""
        fixed_date = date(2027, 5, 20)
        transport = MockMCPTransport(anchor_date=fixed_date)
        clock = transport.get_clock()
        self.assertTrue(clock["is_open"])
        self.assertTrue(clock["timestamp"].startswith("2027-05-20"))
        self.assertTrue(clock["next_open"].startswith("2027-05-21"))



class TestAlpacaGatewayFacade(unittest.TestCase):
    """Pruebas del Interface Contract unificado en AlpacaGateway."""

    def setUp(self):
        self.gateway = AlpacaGateway(mode="mock")

    def test_get_account_returns_typed_account_snapshot(self):
        snapshot = self.gateway.get_account()
        self.assertIsInstance(snapshot, AccountSnapshot)
        self.assertEqual(snapshot.portfolio_value, Decimal("100000.00"))
        self.assertEqual(snapshot.cash, Decimal("50000.00"))
        self.assertEqual(snapshot.buying_power, Decimal("100000.00"))
        self.assertTrue(snapshot.is_active)
        self.assertFalse(snapshot.is_frozen)

    def test_get_clock_returns_typed_market_clock(self):
        clock = self.gateway.get_clock()
        self.assertIsInstance(clock, MarketClockInfo)
        self.assertTrue(clock.is_open)
        self.assertTrue(len(clock.next_open) > 0)
        self.assertTrue(len(clock.next_close) > 0)

    def test_get_option_chain_returns_typed_option_contracts(self):
        chain = self.gateway.get_option_chain("SPY", min_dte=5, max_dte=20)
        self.assertTrue(len(chain) > 0)

        for contract in chain:
            self.assertIsInstance(contract, OptionContract)
            self.assertEqual(contract.underlying_symbol, "SPY")
            self.assertTrue(5 <= contract.dte <= 20)
            self.assertIsInstance(contract.strike_price, Decimal)
            self.assertIsInstance(contract.bid_price, Decimal)
            self.assertIsInstance(contract.ask_price, Decimal)
            self.assertIsInstance(contract.greeks.delta, Decimal)
            self.assertIsInstance(contract.greeks.theta, Decimal)

    def test_submit_option_order_validates_and_executes(self):
        res = self.gateway.submit_option_order(
            symbol="SPY260930C00500000",
            qty=4,
            side="buy",
            time_in_force="day",
        )
        self.assertIsInstance(res, dict)
        self.assertEqual(res["status"], "filled")
        self.assertEqual(res["qty"], "4")

    def test_submit_option_order_zero_qty_raises_order_error(self):
        with self.assertRaises(OptionOrderError):
            self.gateway.submit_option_order(
                symbol="SPY260930C00500000",
                qty=0,
                side="buy",
            )

    def test_mode_selection(self):
        gw_mock = AlpacaGateway(mode="mock")
        self.assertIsInstance(gw_mock.transport, MockMCPTransport)

        with patch("shutil.which", return_value="/usr/bin/alpaca"):
            gw_cli = AlpacaGateway(mode="cli")
            self.assertIsInstance(gw_cli.transport, CLITransport)

        with self.assertRaises(GatewayInitializationError):
            AlpacaGateway(mode="unknown_mode")


class TestStdioMCPTransportRobustness(unittest.TestCase):
    """Pruebas de tolerancia a fallos, reintentos y reconexión en StdioMCPTransport."""

    def test_stdio_missing_command_raises_transport_error(self):
        with patch("shutil.which", return_value=None):
            transport = StdioMCPTransport(command="nonexistent_mcp_cmd")
            with self.assertRaises(MCPTransportError):
                transport.initialize()

    @patch("shutil.which", return_value="/usr/bin/npx")
    @patch("subprocess.Popen")
    def test_stdio_retry_and_reconnect_on_broken_pipe(self, mock_popen, mock_which):
        # Simular que el primer intento falla con BrokenPipeError y el segundo tiene éxito
        proc_fail = MagicMock()
        proc_fail.poll.return_value = None
        proc_fail.stdin.write.side_effect = BrokenPipeError("Pipe broken")

        proc_success = MagicMock()
        proc_success.poll.return_value = None
        fake_response = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"cash": "100000.00"}}) + "\n"
        proc_success.stdout.readline.return_value = fake_response

        mock_popen.side_effect = [proc_fail, proc_success]

        transport = StdioMCPTransport(
            command="npx",
            args=["-y", "@alpacahq/mcp-server-alpaca"],
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        transport.initialize()

        res = transport._send_jsonrpc_request("tools/call", {"name": "get_account", "arguments": {}})
        self.assertEqual(res.get("cash"), "100000.00")
        self.assertEqual(mock_popen.call_count, 2)

    @patch("shutil.which", return_value="/usr/bin/npx")
    @patch("subprocess.Popen")
    def test_stdio_max_retries_exhausted_raises_closed_error(self, mock_popen, mock_which):
        proc_fail = MagicMock()
        proc_fail.poll.return_value = None
        proc_fail.stdin.write.side_effect = BrokenPipeError("Pipe broken")
        mock_popen.return_value = proc_fail

        transport = StdioMCPTransport(
            command="npx",
            args=["-y", "@alpacahq/mcp-server-alpaca"],
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        transport.initialize()

        with self.assertRaises(MCPConnectionClosedError):
            transport._send_jsonrpc_request("tools/call", {"name": "get_account", "arguments": {}})

    def test_stdio_read_line_safe_eof(self):
        """Verifica que _read_line_safe retorne cadena vacía al encontrar EOF en el stream."""
        transport = StdioMCPTransport()
        mock_stream = MagicMock()
        mock_stream.readline.return_value = ""
        line = transport._read_line_safe(mock_stream, timeout=1.0)
        self.assertEqual(line, "")

    def test_stdio_read_line_safe_skips_blank_and_debug_lines(self):
        """Verifica que _read_line_safe descarte líneas en blanco y salidas de log no-JSON antes del JSON-RPC."""
        transport = StdioMCPTransport()
        mock_stream = MagicMock()
        valid_json = '{"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n'
        mock_stream.readline.side_effect = [
            "\n",
            "   \n",
            "[DEBUG] Server starting on port 9000...\n",
            "info: connection established\n",
            valid_json,
        ]
        line = transport._read_line_safe(mock_stream, timeout=1.0)
        self.assertEqual(line, valid_json)

    def test_stdio_read_line_safe_timeout(self):
        """Verifica que _read_line_safe lance TimeoutError si el tiempo límite expira."""
        transport = StdioMCPTransport()
        mock_stream = MagicMock()
        # Simular que readline tarda o que select no devuelve datos dentro del timeout
        mock_stream.fileno.return_value = -1  # Evita llamada a select real
        with patch("time.time", side_effect=[0.0, 5.0, 15.0]):
            with self.assertRaises(TimeoutError):
                transport._read_line_safe(mock_stream, timeout=1.0)

    def test_stdio_cleanup_closes_stream_descriptors(self):
        """Verifica que _cleanup_process cierre adecuadamente stdin, stdout y stderr."""
        transport = StdioMCPTransport()
        mock_proc = MagicMock()
        transport._proc = mock_proc

        transport._cleanup_process()
        mock_proc.stdin.close.assert_called_once()
        mock_proc.stdout.close.assert_called_once()
        mock_proc.stderr.close.assert_called_once()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(transport._proc)



class TestAccountModuleGatewayIntegration(unittest.TestCase):
    """Pruebas de integración asegurando que src/account.py utiliza AlpacaGateway."""

    def test_get_account_snapshot_routes_through_gateway(self):
        mock_gateway = AlpacaGateway(mode="mock")
        snapshot = get_account_snapshot(client=mock_gateway)
        self.assertIsInstance(snapshot, AccountSnapshot)
        self.assertEqual(snapshot.portfolio_value, Decimal("100000.00"))
        self.assertEqual(snapshot.cash, Decimal("50000.00"))

    def test_get_market_clock_routes_through_gateway(self):
        mock_gateway = AlpacaGateway(mode="mock")
        clock = get_market_clock(client=mock_gateway)
        self.assertIsInstance(clock, MarketClockInfo)
        self.assertTrue(clock.is_open)

    def test_get_account_snapshot_default_instantiation(self):
        # Al no pasar cliente, get_account_snapshot debe instanciar AlpacaGateway automáticamente
        snapshot = get_account_snapshot()
        self.assertIsInstance(snapshot, AccountSnapshot)
        self.assertTrue(snapshot.portfolio_value > Decimal("0.0"))

    def test_backward_compatibility_with_legacy_mock_objects(self):
        legacy_mock = MagicMock()
        legacy_mock.get_account.return_value = SimpleNamespace(
            account_id="legacy-id-777",
            cash="12345.67",
            portfolio_value="54321.00",
            buying_power="25000.00",
            equity="54321.00",
            status="ACTIVE",
        )
        snapshot = get_account_snapshot(client=legacy_mock)
        self.assertEqual(snapshot.account_id, "legacy-id-777")
        self.assertEqual(snapshot.cash, Decimal("12345.67"))
        self.assertEqual(snapshot.portfolio_value, Decimal("54321.00"))


if __name__ == "__main__":
    unittest.main()
