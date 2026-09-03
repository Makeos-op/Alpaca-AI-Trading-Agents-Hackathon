"""
Módulo de Bitácora Estructurada de Operaciones y Auditoría (LOG de trade).
Registra tanto trades aprobados/ejecutados como cancelados/rechazados en formato JSONL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from src.indicators.technicals import to_decimal
from src.options.models import OptionContract
from src.risk.risk_engine import RiskVerdict, TradeProposal


@dataclass(frozen=True)
class TradeLogEntry:
    """Registro inmutable de auditoría para una propuesta de trade y su desenlace."""
    timestamp: str
    event_type: str  # "TRADE_EXECUTED" | "TRADE_REJECTED"
    ticker: str
    option_symbol: str
    contract_type: str
    strike_price: Decimal
    expiration_date: str
    dte: int
    quantity: int
    trade_cost: Decimal
    strategy_name: str
    action: str  # BUY / SELL
    is_approved: bool
    risk_reasons: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    portfolio_risk_pct_used: Decimal = Decimal("0.0")
    order_id: Optional[str] = None
    execution_status: str = "REJECTED"  # FILLED / PENDING / REJECTED / ERROR
    fill_price: Optional[Decimal] = None
    greeks: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte la entrada a un diccionario serializable a JSON con valores Decimal en string."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "ticker": self.ticker,
            "option_symbol": self.option_symbol,
            "contract_type": self.contract_type,
            "strike_price": str(self.strike_price),
            "expiration_date": self.expiration_date,
            "dte": self.dte,
            "quantity": self.quantity,
            "trade_cost": str(self.trade_cost),
            "strategy_name": self.strategy_name,
            "action": self.action,
            "is_approved": self.is_approved,
            "risk_reasons": self.risk_reasons,
            "risk_warnings": self.risk_warnings,
            "portfolio_risk_pct_used": str(self.portfolio_risk_pct_used),
            "order_id": self.order_id,
            "execution_status": self.execution_status,
            "fill_price": str(self.fill_price) if self.fill_price is not None else None,
            "greeks": self.greeks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeLogEntry:
        """Reconstruye una entrada a partir de un diccionario JSON."""
        return cls(
            timestamp=data.get("timestamp", ""),
            event_type=data.get("event_type", "UNKNOWN"),
            ticker=data.get("ticker", ""),
            option_symbol=data.get("option_symbol", ""),
            contract_type=data.get("contract_type", "CALL"),
            strike_price=to_decimal(data.get("strike_price", "0.0")),
            expiration_date=data.get("expiration_date", ""),
            dte=int(data.get("dte", 0)),
            quantity=int(data.get("quantity", 0)),
            trade_cost=to_decimal(data.get("trade_cost", "0.0")),
            strategy_name=data.get("strategy_name", ""),
            action=data.get("action", "BUY"),
            is_approved=bool(data.get("is_approved", False)),
            risk_reasons=data.get("risk_reasons", []),
            risk_warnings=data.get("risk_warnings", []),
            portfolio_risk_pct_used=to_decimal(data.get("portfolio_risk_pct_used", "0.0")),
            order_id=data.get("order_id"),
            execution_status=data.get("execution_status", "REJECTED"),
            fill_price=to_decimal(data["fill_price"]) if data.get("fill_price") is not None else None,
            greeks=data.get("greeks", {}),
        )


class TradeLogger:
    """Gestor de auditoría y escritura en bitácora de trades (JSONL)."""

    def __init__(self, log_file_path: Optional[str | Path] = None):
        if log_file_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            log_dir = project_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = log_dir / "trades.jsonl"
        else:
            self.log_file = Path(log_file_path)
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_executed_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
        order_id: str,
        fill_price: Optional[Decimal] = None,
        status: str = "FILLED",
    ) -> TradeLogEntry:
        """Registra una orden de opciones aprobada y ejecutada en Alpaca."""
        contract = proposal.contract
        now_iso = datetime.now(timezone.utc).isoformat()

        entry = TradeLogEntry(
            timestamp=now_iso,
            event_type="TRADE_EXECUTED",
            ticker=contract.underlying_symbol,
            option_symbol=contract.symbol,
            contract_type=contract.contract_type.value,
            strike_price=contract.strike_price,
            expiration_date=contract.expiration_date,
            dte=contract.dte,
            quantity=proposal.quantity,
            trade_cost=verdict.trade_cost,
            strategy_name=proposal.strategy_name,
            action=proposal.action,
            is_approved=True,
            risk_reasons=verdict.reasons,
            risk_warnings=verdict.warnings,
            portfolio_risk_pct_used=verdict.portfolio_risk_pct_used,
            order_id=order_id,
            execution_status=status,
            fill_price=fill_price or contract.ask_price,
            greeks=contract.greeks.to_dict(),
        )

        self._append_to_file(entry)
        return entry

    def log_rejected_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
    ) -> TradeLogEntry:
        """Registra una propuesta de trade rechazada o cancelada por el Risk Engine."""
        contract = proposal.contract
        now_iso = datetime.now(timezone.utc).isoformat()

        entry = TradeLogEntry(
            timestamp=now_iso,
            event_type="TRADE_REJECTED",
            ticker=contract.underlying_symbol,
            option_symbol=contract.symbol,
            contract_type=contract.contract_type.value,
            strike_price=contract.strike_price,
            expiration_date=contract.expiration_date,
            dte=contract.dte,
            quantity=proposal.quantity,
            trade_cost=verdict.trade_cost,
            strategy_name=proposal.strategy_name,
            action=proposal.action,
            is_approved=False,
            risk_reasons=verdict.reasons,
            risk_warnings=verdict.warnings,
            portfolio_risk_pct_used=verdict.portfolio_risk_pct_used,
            order_id=None,
            execution_status="REJECTED",
            fill_price=None,
            greeks=contract.greeks.to_dict(),
        )

        self._append_to_file(entry)
        return entry

    def _append_to_file(self, entry: TradeLogEntry) -> None:
        """Escribe la entrada como una línea JSON en el archivo log."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def get_trade_history(self, limit: int = 50) -> list[TradeLogEntry]:
        """Lee y parsea las últimas N entradas de la bitácora."""
        if not self.log_file.exists():
            return []

        entries: list[TradeLogEntry] = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        data = json.loads(line_str)
                        entries.append(TradeLogEntry.from_dict(data))
                    except (json.JSONDecodeError, Exception):
                        continue

        return entries[-limit:]
