"""
Espera al open real del mercado (consultando el reloj de Alpaca vía MCP/CLI,
no una hora fija) y luego lanza el loop de trading en vivo, sin intervención
manual. Pensado para dejarlo corriendo desatendido antes de la apertura.

Uso:
    python scripts/wait_for_open_and_trade.py \
        --tickers SPY,AAPL,MSFT --timeframe 1Min --interval 60 \
        --deadline "2026-09-04T10:00:00-05:00"

--deadline es opcional: si se da, el proceso se detiene solo a esa hora
(ademas de poder pararlo con Ctrl+C), util para no dejarlo corriendo de mas
despues de la entrega.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from src.execution.mcp_gateway import AlpacaGateway  # noqa: E402


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def wait_for_market_open(poll_seconds: int = 30) -> None:
    """Bloquea hasta que el reloj real de Alpaca reporte el mercado abierto."""
    gw = AlpacaGateway(mode="auto")
    print(f"[{datetime.now(timezone.utc).isoformat()}] Consultando reloj real de Alpaca...")

    while True:
        try:
            clock = gw.get_clock()
        except Exception as exc:
            print(f"  * Error consultando el reloj ({exc}). Reintentando en {poll_seconds}s...")
            time.sleep(poll_seconds)
            continue

        if clock.is_open:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Mercado ABIERTO. Lanzando trading en vivo.")
            return

        next_open_str = clock.next_open
        try:
            next_open = _parse_iso(next_open_str)
            now = datetime.now(next_open.tzinfo)
            remaining = (next_open - now).total_seconds()
        except Exception:
            remaining = None

        if remaining is not None and remaining > 0:
            # Duerme en bloques para poder reaccionar a Ctrl+C y no perder
            # precisión si el próximo open cambia (feriado, etc.)
            sleep_for = min(remaining, 900)  # nunca duerme más de 15 min de una
            print(
                f"  * Mercado cerrado. Próxima apertura: {next_open_str} "
                f"(~{int(remaining // 60)} min restantes). Durmiendo {int(sleep_for)}s..."
            )
            time.sleep(max(5, sleep_for))
        else:
            print(f"  * Mercado cerrado, sin next_open válido aún. Reintentando en {poll_seconds}s...")
            time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Espera al open real y lanza el trading loop en vivo")
    parser.add_argument("--tickers", type=str, default="SPY,AAPL,MSFT")
    parser.add_argument("--timeframe", choices=["1Min", "5Min", "15Min"], default="1Min")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--asset-type", choices=["auto", "option", "equity"], default="auto")
    parser.add_argument(
        "--deadline",
        type=str,
        default=None,
        help="ISO 8601 con offset (ej. 2026-09-04T10:00:00-05:00). Si se pasa, el "
        "proceso corta el loop de trading a esa hora exacta.",
    )
    args = parser.parse_args()

    wait_for_market_open()

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "src" / "main.py"),
        "--mode", "scalp",
        "--timeframe", args.timeframe,
        "--interval", str(args.interval),
        "--tickers", args.tickers,
        "--asset-type", args.asset_type,
        "--continuous",
    ]
    print(f"[{datetime.now(timezone.utc).isoformat()}] Ejecutando: {' '.join(cmd)}")

    env = os.environ.copy()
    proc = subprocess.Popen(cmd, env=env, cwd=str(PROJECT_ROOT))

    if args.deadline:
        deadline_dt = _parse_iso(args.deadline)
        while True:
            now = datetime.now(deadline_dt.tzinfo)
            if now >= deadline_dt:
                print(f"[{datetime.now(timezone.utc).isoformat()}] Deadline alcanzado ({args.deadline}). Deteniendo el loop.")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            if proc.poll() is not None:
                print("El proceso de trading terminó por su cuenta antes del deadline.")
                break
            time.sleep(min(30, (deadline_dt - now).total_seconds()))
    else:
        proc.wait()


if __name__ == "__main__":
    main()
