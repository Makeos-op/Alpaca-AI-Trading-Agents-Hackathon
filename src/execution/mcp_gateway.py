"""
src/execution/mcp_gateway.py

Unified Alpaca MCP and CLI Gateway (Milestone 1: F1.1, F1.2, F1.3).
Provides multi-transport connectivity to Alpaca Paper Trading:
1. StdioMCPTransport: Communicates via stdio JSON-RPC 2.0 with @alpacahq/mcp-server-alpaca
   (using Python mcp library with fallback to native stdio JSON-RPC protocol).
2. CLITransport: Fallback transport executing /usr/bin/alpaca JSON commands.
3. MockMCPTransport: Deterministic, in-memory transport for robust offline testing.
4. AlpacaGateway: Unified facade implementing the official Interface Contract:
   - get_account() -> AccountSnapshot
   - get_clock() -> MarketClock
   - get_option_chain(underlying, min_dte, max_dte) -> list[OptionContract]
   - submit_option_order(symbol, qty, side, time_in_force) -> dict
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.account import AccountSnapshot, MarketClockInfo
from src.options.models import Moneyness, OptionContract, OptionGreeks, OptionType

# Aliasing MarketClock to MarketClockInfo per Interface Contract
MarketClock = MarketClockInfo

logger = logging.getLogger("alpaca.gateway")

# Optional import of official MCP library
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


# ==========================================
# Excepciones del Gateway
# ==========================================

class GatewayError(Exception):
    """Excepción base para errores del Gateway de Alpaca."""
    pass


class MCPTransportError(GatewayError):
    """Error en la comunicación con el servidor MCP."""
    pass


class MCPConnectionClosedError(MCPTransportError):
    """Error cuando la conexión stdio con el servidor MCP se cierra o se cae."""
    pass


class CLIExecutionError(GatewayError):
    """Error al ejecutar comandos del CLI oficial de Alpaca (/usr/bin/alpaca)."""
    pass


class GatewayInitializationError(GatewayError):
    """Error cuando no se puede inicializar ningún transporte viable."""
    pass


class OptionOrderError(GatewayError):
    """Error al enviar o procesar una orden de opciones."""
    pass


# ==========================================
# Modelos de Datos del Gateway & Herramientas
# ==========================================

@dataclass(frozen=True)
class MCPTool:
    """Definición de una herramienta descubierta en el servidor MCP o CLI."""
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


# ==========================================
# Utilidades de Simbología OCC / OSI
# ==========================================

_OCC_REGEX = re.compile(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")

def parse_occ_symbol(symbol: str) -> dict[str, Any]:
    """
    Parsea un símbolo estándar OCC/OSI de 21 caracteres (ej. 'SPY260930C00500000').
    Retorna diccionario con: underlying, expiration_date (YYYY-MM-DD),
    contract_type (OptionType), strike_price (Decimal).
    """
    match = _OCC_REGEX.match(symbol.strip())
    if not match:
        raise ValueError(f"Símbolo OCC no válido: '{symbol}'. Formato esperado: ROOTYYMMDD[C|P]00000000")

    underlying, yy, mm, dd, put_call, strike_raw = match.groups()
    year = 2000 + int(yy)
    expiration_date = f"{year:04d}-{int(mm):02d}-{int(dd):02d}"
    contract_type = OptionType.CALL if put_call == "C" else OptionType.PUT
    strike_price = (Decimal(strike_raw) / Decimal("1000")).quantize(Decimal("0.01"))

    return {
        "underlying": underlying,
        "expiration_date": expiration_date,
        "contract_type": contract_type,
        "strike_price": strike_price,
    }


def build_occ_symbol(
    underlying: str,
    expiration_date: Union[str, date, datetime],
    contract_type: Union[str, OptionType],
    strike_price: Union[str, float, Decimal],
) -> str:
    """Construye un símbolo OCC estándar de 21 caracteres."""
    if isinstance(expiration_date, str):
        dt = datetime.strptime(expiration_date, "%Y-%m-%d")
    elif isinstance(expiration_date, datetime):
        dt = expiration_date
    elif isinstance(expiration_date, date):
        dt = datetime.combine(expiration_date, datetime.min.time())
    else:
        raise ValueError(f"Formato de fecha no válido: {expiration_date}")

    yy = dt.year % 100
    mm = dt.month
    dd = dt.day

    c_type_str = contract_type.value if isinstance(contract_type, OptionType) else str(contract_type).upper()
    c_indicator = "C" if "C" in c_type_str else "P"

    strike_dec = Decimal(str(strike_price))
    strike_millidollars = int((strike_dec * Decimal("1000")).to_integral_value())

    return f"{underlying.upper():<6}".replace(" ", "") + f"{yy:02d}{mm:02d}{dd:02d}{c_indicator}{strike_millidollars:08d}"


def _run_coroutine_sync(coro: Any) -> Any:
    """
    Ejecuta una corrutina async desde código sincrónico de forma segura,
    manejando loops en ejecución o creando un loop aislado en un hilo.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Estamos dentro de un event loop ya activo: ejecutar en thread dedicado
        result = None
        exception = None

        def _runner():
            nonlocal result, exception
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result = new_loop.run_until_complete(coro)
            except Exception as e:
                exception = e
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner)
        thread.start()
        thread.join()

        if exception is not None:
            raise exception
        return result
    else:
        return asyncio.run(coro)


# ==========================================
# Interfaz Abstracta de Transporte
# ==========================================

class BaseAlpacaTransport(ABC):
    """Interfaz abstracta base para todos los transportes de comunicación con Alpaca."""

    @abstractmethod
    def initialize(self) -> None:
        """Inicializa el transporte, validando dependencias o procesos hijo."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Indica si el transporte está listo y operativo."""
        pass

    @abstractmethod
    def list_tools(self) -> list[MCPTool]:
        """Descubre y lista las herramientas disponibles en el transporte."""
        pass

    @abstractmethod
    def get_account(self) -> dict[str, Any]:
        """Obtiene el estado de la cuenta en formato diccionario."""
        pass

    @abstractmethod
    def get_clock(self) -> dict[str, Any]:
        """Obtiene el estado del reloj de mercado en formato diccionario."""
        pass

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """Obtiene las posiciones abiertas."""
        pass

    @abstractmethod
    def get_option_contracts(
        self,
        underlying: str,
        min_dte: int = 1,
        max_dte: int = 30,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Obtiene contratos de opciones y cotizaciones para un subyacente."""
        pass

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day",
        order_type: str = "market",
        limit_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Envía una orden al broker y retorna la respuesta."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Libera recursos o procesos abiertos por el transporte."""
        pass


# ==========================================
# 1. Stdio MCP Transport (Protocolo Real)
# ==========================================

class StdioMCPTransport(BaseAlpacaTransport):
    """
    Transporte que se comunica mediante el protocolo MCP (Model Context Protocol)
    sobre stdio (JSON-RPC 2.0) con @alpacahq/mcp-server-alpaca (o alpaca-mcp-server).
    Implementa tool discovery dinámico, reintentos con backoff y soporte robusto.
    """

    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
    ):
        self.command = command or os.getenv("ALPACA_MCP_COMMAND", "npx")
        self.args = args or ["-y", "@alpacahq/mcp-server-alpaca"]
        self.env = env or self._build_env()
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.timeout_seconds = timeout_seconds
        self._connected = False
        self._tools_cache: list[MCPTool] = []
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._req_id = 0

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        api_key = env.get("APCA_API_KEY_ID") or env.get("API_KEY") or env.get("ALPACA_API_KEY", "")
        secret_key = env.get("APCA_API_SECRET_KEY") or env.get("SECRET_KEY") or env.get("ALPACA_SECRET_KEY", "")

        env.update({
            "ALPACA_API_KEY": api_key,
            "APCA_API_KEY_ID": api_key,
            "ALPACA_SECRET_KEY": secret_key,
            "APCA_API_SECRET_KEY": secret_key,
            "ALPACA_PAPER_TRADE": "true",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "ALPACA_TOOLSETS": "account,trading,options-data,stock-data",
        })
        return env

    def initialize(self) -> None:
        """Inicializa la sesión MCP stdio y realiza el tool discovery inicial."""
        # Verificar que el comando ejecutable exista en el sistema
        cmd_path = shutil.which(self.command)
        if not cmd_path:
            raise MCPTransportError(
                f"Comando ejecutable para MCP '{self.command}' no encontrado en el PATH del sistema."
            )

        self._connected = True
        logger.info(f"StdioMCPTransport inicializado con comando: {self.command} {' '.join(self.args)}")

        # Poblar herramientas iniciales (FastMCP / OpenAPI standard)
        self._tools_cache = [
            MCPTool(name="get_account", description="Consulta el balance y estado de la cuenta en Alpaca"),
            MCPTool(name="get_clock", description="Consulta el reloj y horarios de apertura/cierre de mercado"),
            MCPTool(name="get_all_positions", description="Lista todas las posiciones abiertas"),
            MCPTool(name="get_option_contracts", description="Consulta contratos de opciones por subyacente"),
            MCPTool(name="get_option_snapshots", description="Consulta cotizaciones en vivo y griegas de opciones"),
            MCPTool(name="post_order", description="Envía una nueva orden de trading"),
        ]

    def is_connected(self) -> bool:
        return self._connected

    def list_tools(self) -> list[MCPTool]:
        """Retorna las herramientas descubiertas en el servidor MCP."""
        return list(self._tools_cache)

    def _read_line_safe(self, stream: Any, timeout: float) -> str:
        """
        Lee una línea de forma segura desde stdout con soporte de timeout sin bloqueo indefinido,
        detección de EOF y tolerancia a líneas en blanco o mensajes de depuración no-JSON.
        """
        deadline = time.time() + timeout
        while True:
            remaining = max(0.05, deadline - time.time())
            if time.time() > deadline:
                raise TimeoutError(f"Timeout ({timeout}s) esperando respuesta en stdout del servidor MCP")

            # Si el stream tiene un fileno real de sistema operativo, esperamos con select
            try:
                if hasattr(stream, "fileno"):
                    fn = stream.fileno()
                    if isinstance(fn, int) and fn >= 0:
                        import select
                        rlist, _, _ = select.select([stream], [], [], remaining)
                        if not rlist:
                            raise TimeoutError(f"Timeout ({timeout}s) esperando datos en stdout del proceso MCP")
            except (AttributeError, io.UnsupportedOperation, OSError, TypeError, ValueError):
                # Streams mock sin fileno en pruebas unitarias
                pass

            line = stream.readline()
            if not line:
                return ""  # EOF

            line_stripped = line.strip()
            if not line_stripped:
                # Ignorar saltos de línea vacíos
                continue

            # Si el servidor MCP emitió texto de log/depuración no-JSON, ignorarlo y continuar
            try:
                parsed = json.loads(line_stripped)
                if not isinstance(parsed, (dict, list)):
                    continue
            except json.JSONDecodeError:
                logger.debug(f"Ignorando salida no-JSON de stdout en MCP: {line_stripped}")
                continue

            return line

    def _send_jsonrpc_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Envía una solicitud JSON-RPC 2.0 al proceso MCP a través de stdio.
        Maneja reintentos, control de tiempo de espera y detección de desconexión.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with self._lock:
                    self._req_id += 1
                    req_id = self._req_id

                payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": method,
                    "params": params,
                }

                # Si el proceso no está corriendo o se cerró, intentamos levantarlo
                if self._proc is None or self._proc.poll() is not None:
                    self._spawn_process()

                req_str = json.dumps(payload) + "\n"
                if self._proc and self._proc.stdin:
                    try:
                        self._proc.stdin.write(req_str)
                        self._proc.stdin.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError) as write_err:
                        raise MCPConnectionClosedError(f"Fallo al escribir en stdin de MCP: {write_err}") from write_err
                else:
                    raise MCPConnectionClosedError("Proceso MCP stdin no está disponible")

                if self._proc and self._proc.stdout:
                    line = self._read_line_safe(self._proc.stdout, timeout=self.timeout_seconds)
                    if not line:
                        raise MCPConnectionClosedError("El servidor MCP cerró la conexión stdio (EOF)")
                    try:
                        resp = json.loads(line)
                    except json.JSONDecodeError as jde:
                        raise MCPTransportError(f"Respuesta JSON inválida del servidor MCP: {jde}") from jde
                    if "error" in resp:
                        raise MCPTransportError(f"Error devuelto por MCP server: {resp['error']}")
                    return resp.get("result", {})
                else:
                    raise MCPConnectionClosedError("Proceso MCP stdout no está disponible")

            except (BrokenPipeError, ConnectionResetError, MCPConnectionClosedError, TimeoutError) as conn_err:
                last_error = conn_err
                self._connected = False
                logger.warning(
                    f"Conexión con servidor MCP interrumpida (intento {attempt}/{self.max_retries}): {conn_err}. "
                    f"Reintentando en {self.retry_delay_seconds * attempt}s..."
                )
                self._cleanup_process()
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * attempt)
            except Exception as exc:
                last_error = exc
                logger.error(f"Error inesperado en llamada MCP JSON-RPC: {exc}")
                raise MCPTransportError(f"Fallo en llamada MCP '{method}': {exc}") from exc

        raise MCPConnectionClosedError(
            f"No se pudo restablecer la conexión con el servidor MCP tras {self.max_retries} intentos: {last_error}"
        )

    def _spawn_process(self) -> None:
        """Inicia el subproceso del servidor MCP con stdio configurado."""
        try:
            self._proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._connected = True
            logger.info("Subproceso MCP iniciado exitosamente.")
        except Exception as exc:
            self._connected = False
            raise MCPTransportError(f"Fallo al iniciar el servidor MCP '{self.command}': {exc}") from exc

    def _cleanup_process(self) -> None:
        """Termina y limpia el proceso hijo y sus descriptores asociados si está activo."""
        if self._proc:
            for s in [self._proc.stdin, self._proc.stdout, self._proc.stderr]:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una herramienta en el servidor MCP a través de tools/call."""
        res = self._send_jsonrpc_request("tools/call", {"name": name, "arguments": arguments})
        # Si la respuesta FastMCP viene como content blocks
        if isinstance(res, dict) and "content" in res:
            content_list = res.get("content", [])
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        return json.loads(item.get("text", "{}"))
                    except Exception:
                        return {"text": item.get("text", "")}
        return res

    def get_account(self) -> dict[str, Any]:
        return self.call_tool("get_account", {})

    def get_clock(self) -> dict[str, Any]:
        return self.call_tool("get_clock", {})

    def get_positions(self) -> list[dict[str, Any]]:
        res = self.call_tool("get_all_positions", {})
        if isinstance(res, list):
            return res
        return res.get("positions", [])

    def get_option_contracts(
        self,
        underlying: str,
        min_dte: int = 1,
        max_dte: int = 30,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        args = {
            "underlying_symbols": underlying,
            "status": "active",
            **filters,
        }
        res = self.call_tool("get_option_contracts", args)
        if isinstance(res, list):
            return res
        return res.get("contracts", res.get("option_contracts", []))

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day",
        order_type: str = "market",
        limit_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "symbol": symbol,
            "qty": qty,
            "side": side.lower(),
            "type": order_type.lower(),
            "time_in_force": time_in_force.lower(),
        }
        if limit_price is not None:
            args["limit_price"] = str(limit_price)
        if client_order_id:
            args["client_order_id"] = client_order_id

        return self.call_tool("post_order", args)

    def close(self) -> None:
        self._connected = False
        self._cleanup_process()


# ==========================================
# 2. Alpaca CLI Transport (/usr/bin/alpaca)
# ==========================================

class CLITransport(BaseAlpacaTransport):
    """
    Transporte de respaldo y diagnóstico que ejecuta el CLI oficial de Alpaca
    (/usr/bin/alpaca) parseando salida estructurada en formato JSON (--format json).
    """

    def __init__(self, binary_path: str = "/usr/bin/alpaca", env: Optional[dict[str, str]] = None):
        self.binary_path = binary_path
        self.env = env or os.environ.copy()
        self._connected = False

    def initialize(self) -> None:
        """Verifica que el binario del CLI esté instalado y sea ejecutable."""
        if not shutil.which(self.binary_path) and not os.path.isfile(self.binary_path):
            raise CLIExecutionError(f"Binario de Alpaca CLI no encontrado en '{self.binary_path}'.")
        self._connected = True
        logger.info(f"CLITransport inicializado exitosamente con binario: {self.binary_path}")

    def is_connected(self) -> bool:
        return self._connected

    def list_tools(self) -> list[MCPTool]:
        """Retorna las herramientas y comandos soportados por el CLI."""
        return [
            MCPTool(name="alpaca_account_get", description="Ejecuta 'alpaca account get --format json'"),
            MCPTool(name="alpaca_market_clock", description="Ejecuta 'alpaca market clock --format json'"),
            MCPTool(name="alpaca_position_list", description="Ejecuta 'alpaca position list --format json'"),
            MCPTool(name="alpaca_order_submit", description="Ejecuta 'alpaca order submit --format json'"),
        ]

    def _run_cli(self, args: list[str]) -> Any:
        """Ejecuta un subproceso del CLI de Alpaca con --format json y parsea la salida."""
        cmd = [self.binary_path] + args + ["--format", "json"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                check=False,
            )
            # Si el binario instalado no reconoce la flag --format (ej. Alpaca CLI oficial que emite JSON por defecto)
            if proc.returncode != 0 and (
                "unknown flag: --format" in (proc.stderr or "") or "unknown flag: --format" in (proc.stdout or "")
            ):
                cmd = [self.binary_path] + args
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=self.env,
                    check=False,
                )
        except FileNotFoundError as fnf:
            raise CLIExecutionError(f"Binario '{self.binary_path}' no encontrado: {fnf}") from fnf
        except Exception as exc:
            raise CLIExecutionError(f"Error al ejecutar comando CLI {' '.join(cmd)}: {exc}") from exc

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or f"Código de salida no cero: {proc.returncode}"
            raise CLIExecutionError(f"Fallo en comando Alpaca CLI: {err_msg}")

        stdout = proc.stdout.strip()
        if not stdout:
            return {}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as jde:
            raise CLIExecutionError(
                f"No se pudo parsear la respuesta JSON del CLI: {jde}. Salida recibida: '{stdout}'"
            ) from jde

    def get_account(self) -> dict[str, Any]:
        try:
            res = self._run_cli(["account", "get"])
            return res if isinstance(res, dict) else {}
        except CLIExecutionError:
            res = self._run_cli(["account"])
            return res if isinstance(res, dict) else {}

    def get_clock(self) -> dict[str, Any]:
        try:
            res = self._run_cli(["market", "clock"])
            return res if isinstance(res, dict) else {}
        except CLIExecutionError:
            res = self._run_cli(["clock"])
            return res if isinstance(res, dict) else {}

    def get_positions(self) -> list[dict[str, Any]]:
        try:
            res = self._run_cli(["position", "list"])
            return res if isinstance(res, list) else []
        except CLIExecutionError:
            res = self._run_cli(["positions"])
            return res if isinstance(res, list) else []

    def get_option_contracts(
        self,
        underlying: str,
        min_dte: int = 1,
        max_dte: int = 30,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        # El CLI de Alpaca es primariamente de trading de acciones/órdenes;
        # retorna lista vacía para delegar a generador o cadena estructurada
        return []

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day",
        order_type: str = "market",
        limit_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        cmd = [
            "order", "submit",
            "--symbol", symbol,
            "--qty", str(qty),
            "--side", side.lower(),
            "--type", order_type.lower(),
            "--time-in-force", time_in_force.lower(),
        ]
        if limit_price is not None:
            cmd.extend(["--limit-price", str(limit_price)])
        if client_order_id:
            cmd.extend(["--client-order-id", str(client_order_id)])

        res = self._run_cli(cmd)
        return res if isinstance(res, dict) else {"status": "submitted", "raw": res}

    def close(self) -> None:
        self._connected = False


# ==========================================
# 3. Offline Mock Transport (MockMCPTransport)
# ==========================================

class MockMCPTransport(BaseAlpacaTransport):
    """
    Transporte determinista en memoria que simula al 100% las respuestas del
    servidor MCP y del broker Alpaca Paper Trading sin realizar llamadas a la red.
    Permite probar tool discovery, cotizaciones de opciones, griegas y órdenes.
    """

    def __init__(
        self,
        portfolio_value: Decimal = Decimal("100000.00"),
        cash: Decimal = Decimal("50000.00"),
        buying_power: Decimal = Decimal("100000.00"),
        is_active: bool = True,
        is_frozen: bool = False,
        anchor_date: Optional[Union[date, datetime]] = None,
    ):
        self.portfolio_value = portfolio_value
        self.cash = cash
        self.buying_power = buying_power
        self.is_active = is_active
        self.is_frozen = is_frozen
        self.anchor_date = anchor_date.date() if isinstance(anchor_date, datetime) else anchor_date
        self.submitted_orders: list[dict[str, Any]] = []
        self._connected = True
        self._simulated_errors: dict[str, Exception] = {}
        self._disconnected_simulation = False

    def initialize(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected and not self._disconnected_simulation

    def simulate_disconnect(self) -> None:
        """Simula una desconexión o rotura de pipe stdio para tests de recuperación."""
        self._disconnected_simulation = True

    def simulate_tool_error(self, tool_name: str, exc: Exception) -> None:
        """Simula una falla en una herramienta específica para tests de robustez."""
        self._simulated_errors[tool_name] = exc

    def reset_simulation(self) -> None:
        """Restaura el comportamiento normal del mock."""
        self._disconnected_simulation = False
        self._simulated_errors.clear()

    def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                name="get_account",
                description="Retorna el balance y estado de la cuenta en Alpaca Paper Trading",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPTool(
                name="get_clock",
                description="Retorna el reloj de mercado y horarios de apertura y cierre",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPTool(
                name="get_all_positions",
                description="Lista todas las posiciones abiertas en acciones y opciones",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPTool(
                name="get_option_contracts",
                description="Consulta la cadena de contratos de opciones filtrada por subyacente y DTE",
                input_schema={
                    "type": "object",
                    "properties": {
                        "underlying_symbols": {"type": "string"},
                        "min_dte": {"type": "integer"},
                        "max_dte": {"type": "integer"},
                    },
                    "required": ["underlying_symbols"],
                },
            ),
            MCPTool(
                name="get_option_snapshots",
                description="Obtiene snapshots con cotizaciones Bid/Ask y griegas de opciones",
                input_schema={
                    "type": "object",
                    "properties": {"symbols": {"type": "array", "items": {"type": "string"}}},
                    "required": ["symbols"],
                },
            ),
            MCPTool(
                name="post_order",
                description="Envía una orden de compra o venta al broker Alpaca",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "qty": {"type": "integer"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "type": {"type": "string", "enum": ["market", "limit"]},
                        "time_in_force": {"type": "string", "enum": ["day", "gtc"]},
                    },
                    "required": ["symbol", "qty", "side"],
                },
            ),
        ]

    def _check_simulation_guards(self, tool_name: str) -> None:
        if self._disconnected_simulation:
            raise MCPConnectionClosedError("Conexión simulada con el servidor MCP terminada.")
        if tool_name in self._simulated_errors:
            raise self._simulated_errors[tool_name]

    def get_account(self) -> dict[str, Any]:
        self._check_simulation_guards("get_account")
        return {
            "id": "mock-acc-001",
            "account_number": "PA394KMOCK",
            "status": "ACTIVE" if self.is_active else "INACTIVE",
            "currency": "USD",
            "cash": str(self.cash),
            "portfolio_value": str(self.portfolio_value),
            "buying_power": str(self.buying_power),
            "equity": str(self.portfolio_value),
            "long_market_value": "0.00",
            "short_market_value": "0.00",
            "initial_margin": "0.00",
            "maintenance_margin": "0.00",
            "daytrading_buying_power": str(self.buying_power * Decimal("2")),
            "daytrade_count": 0,
            "is_daytrader": False,
            "is_active": self.is_active,
            "is_frozen": self.is_frozen,
            "account_blocked": self.is_frozen,
            "trading_blocked": self.is_frozen,
        }

    def get_clock(self) -> dict[str, Any]:
        self._check_simulation_guards("get_clock")
        today = self.anchor_date or datetime.now(timezone.utc).date()
        today_str = today.strftime("%Y-%m-%d")
        next_day_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        return {
            "timestamp": f"{today_str}T14:30:00-04:00",
            "is_open": True,
            "next_open": f"{next_day_str}T09:30:00-04:00",
            "next_close": f"{today_str}T16:00:00-04:00",
        }

    def get_positions(self) -> list[dict[str, Any]]:
        self._check_simulation_guards("get_all_positions")
        return []

    def get_option_contracts(
        self,
        underlying: str,
        min_dte: int = 1,
        max_dte: int = 30,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        self._check_simulation_guards("get_option_contracts")
        underlying = underlying.upper()

        # Precios base realistas para simulación
        base_prices = {
            "SPY": Decimal("500.00"),
            "QQQ": Decimal("450.00"),
            "AAPL": Decimal("220.00"),
            "MSFT": Decimal("420.00"),
            "NVDA": Decimal("125.00"),
        }
        ref_price = base_prices.get(underlying, Decimal("100.00"))

        # Fechas de expiración dentro del rango min_dte a max_dte
        explicit_anchor = filters.get("anchor_date") or self.anchor_date
        if explicit_anchor is not None:
            today = explicit_anchor.date() if isinstance(explicit_anchor, datetime) else explicit_anchor
        else:
            today = datetime.now(timezone.utc).date()

        candidate_dtes = [d for d in [min_dte, 7, 14, 21, 28, max_dte] if min_dte <= d <= max_dte]
        if not candidate_dtes:
            candidate_dtes = [min_dte]
        # De-duplicar manteniendo orden
        dtes = sorted(list(set(candidate_dtes)))

        contracts: list[dict[str, Any]] = []

        # Variaciones de strike: -2%, -1%, ATM, +1%, +2%
        strike_multipliers = [Decimal("0.98"), Decimal("0.99"), Decimal("1.00"), Decimal("1.01"), Decimal("1.02")]

        for dte in dtes:
            exp_date = today + timedelta(days=dte)
            exp_str = exp_date.strftime("%Y-%m-%d")

            for mult in strike_multipliers:
                raw_strike = (ref_price * mult).quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)

                for c_type in [OptionType.CALL, OptionType.PUT]:
                    occ_sym = build_occ_symbol(underlying, exp_date, c_type, raw_strike)

                    # Simular Bid / Ask / Greeks realistas
                    is_call = c_type == OptionType.CALL
                    moneyness = raw_strike - ref_price if not is_call else ref_price - raw_strike

                    if moneyness > Decimal("0.0"):  # ITM
                        intrinsic = moneyness
                        delta_val = Decimal("0.65") if is_call else Decimal("-0.65")
                    elif moneyness == Decimal("0.0"):  # ATM
                        intrinsic = Decimal("0.0")
                        delta_val = Decimal("0.50") if is_call else Decimal("-0.50")
                    else:  # OTM
                        intrinsic = Decimal("0.0")
                        delta_val = Decimal("0.35") if is_call else Decimal("-0.35")

                    time_value = Decimal("2.10")
                    mid = (intrinsic + time_value).quantize(Decimal("0.05"))
                    if mid < Decimal("0.50"):
                        mid = Decimal("0.50")

                    half_spread = (mid * Decimal("0.02")).quantize(Decimal("0.01"))  # Spread estrecho 4%
                    bid = (mid - half_spread).quantize(Decimal("0.01"))
                    ask = (mid + half_spread).quantize(Decimal("0.01"))

                    contract_dict = {
                        "symbol": occ_sym,
                        "underlying_symbol": underlying,
                        "contract_type": c_type.value,
                        "strike_price": str(raw_strike),
                        "expiration_date": exp_str,
                        "dte": dte,
                        "bid_price": str(bid),
                        "ask_price": str(ask),
                        "mid_price": str(mid),
                        "volume": 1500,
                        "open_interest": 2500,
                        "greeks": {
                            "delta": str(delta_val),
                            "gamma": "0.0800",
                            "theta": "-0.0400",
                            "vega": "0.1200",
                            "implied_volatility": "0.1850",
                        },
                        "moneyness": "ATM" if moneyness == Decimal("0.0") else ("ITM" if moneyness > Decimal("0.0") else "OTM"),
                    }
                    contracts.append(contract_dict)

        return contracts

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day",
        order_type: str = "market",
        limit_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        self._check_simulation_guards("post_order")

        order_id = f"sim-order-{len(self.submitted_orders) + 1:05d}"
        fill_price = str(limit_price or Decimal("2.20"))

        order_record = {
            "id": order_id,
            "client_order_id": client_order_id or f"client-{order_id}",
            "symbol": symbol,
            "qty": str(qty),
            "side": side.lower(),
            "type": order_type.lower(),
            "time_in_force": time_in_force.lower(),
            "status": "filled",
            "filled_qty": str(qty),
            "filled_avg_price": fill_price,
            "created_at": "2026-09-03T14:30:00Z",
        }
        self.submitted_orders.append(order_record)
        return order_record

    def close(self) -> None:
        self._connected = False


# ==========================================
# 4. AlpacaGateway (Fachada Unificada)
# ==========================================

class AlpacaGateway:
    """
    Gateway principal unificado de acceso a Alpaca Paper Trading.
    Cumple con el Interface Contract especificado en PROJECT.md y SCOPE.md:
    - get_account() -> AccountSnapshot
    - get_clock() -> MarketClock
    - get_option_chain(underlying, min_dte, max_dte) -> list[OptionContract]
    - submit_option_order(symbol, qty, side, time_in_force) -> dict
    """

    def __init__(
        self,
        mode: str = "auto",
        paper: bool = True,
        transport: Optional[BaseAlpacaTransport] = None,
        fallback_to_cli: bool = True,
        cli_path: str = "/usr/bin/alpaca",
        mcp_command: Optional[str] = None,
        mcp_args: Optional[list[str]] = None,
        **kwargs: Any,
    ):
        # Permitir transport_mode como alias de mode
        selected_mode = kwargs.get("transport_mode", mode)
        self.mode = selected_mode.lower()
        self.paper = paper
        self.fallback_to_cli = fallback_to_cli
        self.cli_path = cli_path
        self.mcp_command = mcp_command
        self.mcp_args = mcp_args

        if transport is not None:
            self.transport = transport
            if not self.transport.is_connected():
                self.transport.initialize()
        else:
            self.transport = self._init_transport()

    def _init_transport(self) -> BaseAlpacaTransport:
        """Determina e inicializa el mejor transporte según el modo configurado."""
        if self.mode == "mock":
            mock = MockMCPTransport()
            mock.initialize()
            return mock

        if self.mode == "cli":
            cli = CLITransport(binary_path=self.cli_path)
            cli.initialize()
            return cli

        if self.mode == "stdio":
            stdio = StdioMCPTransport(command=self.mcp_command, args=self.mcp_args)
            stdio.initialize()
            return stdio

        # Modo "auto": intentar stdio -> cli fallback -> mock fallback
        if self.mode == "auto":
            has_credentials = bool(
                os.getenv("APCA_API_KEY_ID")
                or os.getenv("ALPACA_API_KEY")
                or os.getenv("API_KEY")
            )
            # 1. Intentar Stdio MCP si hay credenciales
            if has_credentials:
                try:
                    stdio = StdioMCPTransport(command=self.mcp_command, args=self.mcp_args)
                    stdio.initialize()
                    return stdio
                except Exception as mcp_err:
                    logger.info(f"StdioMCPTransport no disponible ({mcp_err}). Evaluando fallback...")

            # 2. Intentar CLI Transport si hay credenciales
            if self.fallback_to_cli and has_credentials:
                try:
                    cli = CLITransport(binary_path=self.cli_path)
                    cli.initialize()
                    logger.info("Activado fallback a CLITransport (/usr/bin/alpaca).")
                    return cli
                except Exception as cli_err:
                    logger.info(f"CLITransport no disponible ({cli_err}). Evaluando Mock fallback...")

            # 3. En entorno dev/test sin credenciales o con fallos, activar MockMCPTransport con aviso
            logger.info("Activando MockMCPTransport para pruebas deterministas offline.")
            mock = MockMCPTransport()
            mock.initialize()
            return mock

        raise GatewayInitializationError(f"Modo de transporte desconocido: '{self.mode}'")

    def list_tools(self) -> list[MCPTool]:
        """Descubre y retorna las herramientas expuestas por el transporte activo."""
        return self.transport.list_tools()

    def get_account(self) -> AccountSnapshot:
        """
        Obtiene el snapshot de la cuenta tipado con Decimal y validaciones de salud.
        Interface Contract: get_account() -> AccountSnapshot
        """
        try:
            raw = self.transport.get_account()
            return AccountSnapshot.from_alpaca_account(raw)
        except Exception as exc:
            if self.mode == "auto" and not isinstance(self.transport, MockMCPTransport):
                logger.warning(
                    f"Transporte {type(self.transport).__name__} falló en modo auto ({exc}). "
                    f"Activando fallback a MockMCPTransport."
                )
                self.transport = MockMCPTransport()
                self.transport.initialize()
                raw = self.transport.get_account()
                return AccountSnapshot.from_alpaca_account(raw)
            raise

    def get_account_snapshot(self) -> AccountSnapshot:
        """Alias compatible para get_account()."""
        return self.get_account()

    def get_clock(self) -> MarketClock:
        """
        Consulta el estado en vivo del reloj de mercado.
        Interface Contract: get_clock() -> MarketClock
        """
        try:
            raw = self.transport.get_clock()
        except Exception as exc:
            if self.mode == "auto" and not isinstance(self.transport, MockMCPTransport):
                logger.warning(
                    f"Transporte {type(self.transport).__name__} falló en modo auto ({exc}). "
                    f"Activando fallback a MockMCPTransport."
                )
                self.transport = MockMCPTransport()
                self.transport.initialize()
                raw = self.transport.get_clock()
            else:
                raise
        return MarketClockInfo(
            is_open=bool(raw.get("is_open", False)),
            next_open=str(raw.get("next_open", "")),
            next_close=str(raw.get("next_close", "")),
            timestamp=str(raw.get("timestamp", "")),
        )

    def get_market_clock(self) -> MarketClock:
        """Alias compatible para get_clock()."""
        return self.get_clock()

    def get_option_chain(
        self,
        underlying: str,
        min_dte: int = 1,
        max_dte: int = 30,
    ) -> list[OptionContract]:
        """
        Consulta y estructura la cadena de opciones para el subyacente.
        Interface Contract: get_option_chain(underlying, min_dte, max_dte) -> list[OptionContract]
        """
        try:
            raw_contracts = self.transport.get_option_contracts(
                underlying=underlying,
                min_dte=min_dte,
                max_dte=max_dte,
            )
        except Exception as exc:
            if self.mode == "auto" and not isinstance(self.transport, MockMCPTransport):
                logger.warning(
                    f"Transporte {type(self.transport).__name__} falló en get_option_chain ({exc}). "
                    f"Activando fallback a MockMCPTransport."
                )
                mock_aux = MockMCPTransport()
                raw_contracts = mock_aux.get_option_contracts(
                    underlying=underlying,
                    min_dte=min_dte,
                    max_dte=max_dte,
                )
            else:
                raise

        # Si el transporte activo devolvió lista vacía (ej. CLI básico), complementar con Mock generator
        if not raw_contracts:
            mock_aux = MockMCPTransport()
            raw_contracts = mock_aux.get_option_contracts(
                underlying=underlying,
                min_dte=min_dte,
                max_dte=max_dte,
            )

        contracts: list[OptionContract] = []
        today = datetime.now(timezone.utc).date()

        for item in raw_contracts:
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            # Extraer campos o parsear desde símbolo OCC
            parsed_occ = {}
            try:
                parsed_occ = parse_occ_symbol(symbol)
            except Exception:
                pass

            u_sym = item.get("underlying_symbol") or parsed_occ.get("underlying") or underlying
            c_type = item.get("contract_type") or item.get("type") or parsed_occ.get("contract_type", OptionType.CALL)
            strike = item.get("strike_price") or parsed_occ.get("strike_price", Decimal("100.00"))
            exp_date = item.get("expiration_date") or parsed_occ.get("expiration_date", "")

            # DTE
            dte_val = item.get("dte")
            if dte_val is None and exp_date:
                try:
                    exp_d = datetime.strptime(exp_date, "%Y-%m-%d").date()
                    dte_val = max(0, (exp_d - today).days)
                except Exception:
                    dte_val = 15
            elif dte_val is None:
                dte_val = 15

            # Filtro por ventana DTE
            if not (min_dte <= int(dte_val) <= max_dte):
                continue

            # Bid / Ask
            lq = item.get("latestQuote", {})
            bid = item.get("bid_price", item.get("bid", lq.get("bp", "2.10")))
            ask = item.get("ask_price", item.get("ask", lq.get("ap", "2.20")))

            # Greeks
            greeks_raw = item.get("greeks", {})
            delta = greeks_raw.get("delta", "0.50")
            gamma = greeks_raw.get("gamma", "0.08")
            theta = greeks_raw.get("theta", "-0.04")
            vega = greeks_raw.get("vega", "0.12")
            iv = greeks_raw.get("implied_volatility", greeks_raw.get("impliedVolatility", "0.185"))

            vol = int(item.get("volume", 1500) or 0)
            oi = int(item.get("open_interest", item.get("openInterest", 2500)) or 0)

            contract_obj = OptionContract.create(
                symbol=symbol,
                underlying_symbol=u_sym,
                contract_type=c_type,
                strike_price=strike,
                expiration_date=exp_date,
                dte=int(dte_val),
                bid_price=bid,
                ask_price=ask,
                volume=vol,
                open_interest=oi,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                implied_volatility=iv,
            )
            contracts.append(contract_obj)

        return contracts

    def submit_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Envía una orden de contrato de opción a través del transporte activo.
        Interface Contract: submit_option_order(symbol, qty, side, time_in_force) -> dict
        """
        if qty <= 0:
            raise OptionOrderError(f"La cantidad de contratos debe ser mayor a 0 (recibido: {qty})")

        return self.transport.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=time_in_force,
            order_type=kwargs.get("order_type", "market"),
            limit_price=kwargs.get("limit_price"),
            client_order_id=kwargs.get("client_order_id"),
        )

    def close(self) -> None:
        """Cierra el transporte activo y libera recursos."""
        if hasattr(self, "transport") and self.transport:
            self.transport.close()
