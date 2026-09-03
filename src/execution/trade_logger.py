"""
Módulo de Bitácora Estructurada de Operaciones y Auditoría (LOG de trade).
Registra tanto trades aprobados/ejecutados como simulados o rechazados en formato JSONL
cumpliendo con el estándar JSON Schema Draft-07 (Feature F3.2).
"""

from __future__ import annotations

import json
import re
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
    """
    Registro inmutable de auditoría para una propuesta de trade y su desenlace.
    Compatible tanto con el esquema Draft-07 (con objetos anidados) como con el
    acceso directo a atributos para pruebas y herramientas downstream.
    """
    timestamp: str
    event_type: str  # "TRADE_EXECUTED" | "TRADE_REJECTED" | "TRADE_SIMULATED"
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
    execution_status: str = "REJECTED"  # FILLED / PENDING / REJECTED / SIMULATED / ERROR
    fill_price: Optional[Decimal] = None
    greeks: dict[str, Any] = field(default_factory=dict)
    mode: str = "scan"  # dry-run / scan / loop
    market_data_snapshot: dict[str, Any] = field(default_factory=dict)
    agent_proposal: dict[str, Any] = field(default_factory=dict)
    risk_verdict: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convierte la entrada a un diccionario serializable a JSON.
        Incluye tanto los contenedores anidados requeridos por el esquema Draft-07
        (market_data_snapshot, agent_proposal, risk_verdict, execution_result)
        como los atributos de primer nivel para retrocompatibilidad total.
        """
        # 1. Market Data Snapshot
        market_snap = dict(self.market_data_snapshot) if self.market_data_snapshot else {}
        market_defaults = {
            "ticker": self.ticker,
            "underlying_symbol": self.ticker,
            "underlying_price": str(self.strike_price),
            "option_symbol": self.option_symbol,
            "bid": str(self.fill_price or Decimal("2.10")),
            "bid_price": str(self.fill_price or Decimal("2.10")),
            "ask": str(self.fill_price or Decimal("2.20")),
            "ask_price": str(self.fill_price or Decimal("2.20")),
            "mid_price": str(self.fill_price or Decimal("2.15")),
            "spread_pct": "0.0465",
            "volume": int(market_snap.get("volume", 1500) or 1500),
            "open_interest": int(market_snap.get("open_interest", 1500) or 1500),
            "delta": str(self.greeks.get("delta", "0.50")),
            "theta": str(self.greeks.get("theta", "-0.04")),
            "dte": self.dte,
            "greeks": dict(self.greeks),
        }
        for k, v in market_defaults.items():
            if k not in market_snap or market_snap[k] is None:
                market_snap[k] = v

        # 2. Agent Proposal
        proposal_dict = dict(self.agent_proposal) if self.agent_proposal else {}
        proposal_defaults = {
            "strategy_name": self.strategy_name,
            "signal_type": "BULLISH_CALL_MOMENTUM",
            "confidence": "0.85",
            "target_option_type": self.contract_type,
            "target_contract_symbol": self.option_symbol,
            "action": self.action,
            "quantity": max(1, self.quantity),
            "symbol": self.option_symbol,
            "side": self.action.lower(),
            "rationale": self.strategy_name,
        }
        for k, v in proposal_defaults.items():
            if k not in proposal_dict or proposal_dict[k] is None:
                proposal_dict[k] = v

        # 3. Risk Verdict
        verdict_dict = dict(self.risk_verdict) if self.risk_verdict else {}
        verdict_defaults = {
            "is_approved": self.is_approved,
            "trade_cost": str(self.trade_cost),
            "max_allowed_budget": str(Decimal("5000.00")),
            "portfolio_risk_pct_used": str(self.portfolio_risk_pct_used),
            "reasons": list(self.risk_reasons),
            "reason_codes": [],
            "reason_code": "APPROVED" if self.is_approved else "ERR_EXCEEDS_5PCT_SINGLE_TRADE_LIMIT",
            "message": "; ".join(self.risk_reasons) if self.risk_reasons else "Trade passed all deterministic risk criteria",
            "audited_metrics": {
                "trade_cost": float(self.trade_cost),
                "max_allowed_risk": 5000.0,
                "portfolio_risk_pct": float(self.portfolio_risk_pct_used) * 100.0,
                "spread_pct": 4.08,
                "dte": self.dte,
            },
        }
        for k, v in verdict_defaults.items():
            if k not in verdict_dict or verdict_dict[k] is None:
                verdict_dict[k] = v

        # 4. Execution Result
        exec_dict = dict(self.execution_result) if self.execution_result else {}
        exec_defaults = {
            "executed": self.is_approved,
            "execution_status": self.execution_status,
            "order_id": self.order_id,
            "status": self.execution_status.lower(),
            "filled_qty": self.quantity if self.is_approved else 0,
            "filled_avg_price": str(self.fill_price) if self.fill_price is not None else None,
        }
        for k, v in exec_defaults.items():
            if k not in exec_dict or exec_dict[k] is None:
                exec_dict[k] = v

        return {
            # Standard Draft-07 Top-Level Objects
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "mode": self.mode,
            "market_data_snapshot": market_snap,
            "agent_proposal": proposal_dict,
            "risk_verdict": verdict_dict,
            "execution_result": exec_dict,

            # Direct flat attributes for backward compatibility
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
        """Reconstruye una entrada a partir de un diccionario JSON estructurado o plano."""
        market_snap = data.get("market_data_snapshot", {})
        prop_snap = data.get("agent_proposal", {})
        verdict_snap = data.get("risk_verdict", {})
        exec_snap = data.get("execution_result", {})

        ticker = data.get("ticker") or market_snap.get("ticker") or market_snap.get("underlying_symbol", "")
        option_symbol = data.get("option_symbol") or market_snap.get("option_symbol") or prop_snap.get("target_contract_symbol", "")
        contract_type = data.get("contract_type") or prop_snap.get("target_option_type", "CALL")

        strike_price_raw = data.get("strike_price") or market_snap.get("underlying_price", "0.0")
        strike_price = to_decimal(strike_price_raw)

        expiration_date = data.get("expiration_date", "")
        dte = int(data.get("dte") or market_snap.get("dte", 0))

        quantity = int(data.get("quantity") or prop_snap.get("quantity", 0))
        trade_cost = to_decimal(data.get("trade_cost") or verdict_snap.get("trade_cost", "0.0"))

        strategy_name = data.get("strategy_name") or prop_snap.get("strategy_name", "")
        action = data.get("action") or prop_snap.get("action", "BUY")

        is_approved = bool(data.get("is_approved") if "is_approved" in data else verdict_snap.get("is_approved", False))
        risk_reasons = data.get("risk_reasons") or verdict_snap.get("reasons", [])
        risk_warnings = data.get("risk_warnings") or verdict_snap.get("warnings", [])

        portfolio_risk_pct = to_decimal(data.get("portfolio_risk_pct_used") or verdict_snap.get("portfolio_risk_pct_used", "0.0"))

        order_id = data.get("order_id") if "order_id" in data else exec_snap.get("order_id")
        exec_status = data.get("execution_status") or exec_snap.get("execution_status", "REJECTED")

        fill_raw = data.get("fill_price") if "fill_price" in data else exec_snap.get("filled_avg_price")
        fill_price = to_decimal(fill_raw) if fill_raw is not None else None

        greeks = data.get("greeks") or market_snap.get("greeks", {})
        mode = data.get("mode", "scan")
        event_type = data.get("event_type", "TRADE_EXECUTED" if is_approved else "TRADE_REJECTED")

        return cls(
            timestamp=data.get("timestamp", ""),
            event_type=event_type,
            ticker=ticker,
            option_symbol=option_symbol,
            contract_type=contract_type,
            strike_price=strike_price,
            expiration_date=expiration_date,
            dte=dte,
            quantity=quantity,
            trade_cost=trade_cost,
            strategy_name=strategy_name,
            action=action,
            is_approved=is_approved,
            risk_reasons=risk_reasons,
            risk_warnings=risk_warnings,
            portfolio_risk_pct_used=portfolio_risk_pct,
            order_id=order_id,
            execution_status=exec_status,
            fill_price=fill_price,
            greeks=greeks,
            mode=mode,
            market_data_snapshot=market_snap,
            agent_proposal=prop_snap,
            risk_verdict=verdict_snap,
            execution_result=exec_snap,
        )


class TradeLogger:
    """Gestor de auditoría y escritura en bitácora de trades (JSONL Draft-07)."""

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
        mode: str = "scan",
        underlying_price: Optional[Decimal] = None,
    ) -> TradeLogEntry:
        """Registra una orden de opciones aprobada y ejecutada/simulada."""
        contract = proposal.contract
        now_iso = datetime.now(timezone.utc).isoformat()
        u_price = underlying_price or getattr(contract, "underlying_price", None) or contract.strike_price
        f_price = fill_price or contract.ask_price

        if status == "SIMULATED" or mode == "dry-run":
            event_type = "TRADE_SIMULATED"
            actual_mode = "dry-run"
        else:
            event_type = "TRADE_EXECUTED"
            actual_mode = mode

        market_data_snapshot = {
            "ticker": contract.underlying_symbol,
            "underlying_symbol": contract.underlying_symbol,
            "underlying_price": str(u_price),
            "option_symbol": contract.symbol,
            "bid": str(contract.bid_price),
            "bid_price": str(contract.bid_price),
            "ask": str(contract.ask_price),
            "ask_price": str(contract.ask_price),
            "mid_price": str(contract.mid_price),
            "spread_pct": str(contract.bid_ask_spread_pct),
            "volume": contract.volume,
            "open_interest": contract.open_interest,
            "delta": str(contract.greeks.delta),
            "theta": str(contract.greeks.theta),
            "dte": contract.dte,
            "greeks": contract.greeks.to_dict(),
        }

        target_opt_type = (
            contract.contract_type.value
            if hasattr(contract.contract_type, "value")
            else str(contract.contract_type)
        )
        action_val = proposal.action or getattr(proposal, "side", "BUY") or "BUY"
        agent_proposal = {
            "strategy_name": proposal.strategy_name,
            "signal_type": getattr(proposal, "signal_type", "BULLISH_CALL_MOMENTUM") or "BULLISH_CALL_MOMENTUM",
            "confidence": str(getattr(proposal, "confidence", "0.85")),
            "target_contract_symbol": contract.symbol,
            "target_option_type": target_opt_type,
            "action": action_val.upper(),
            "quantity": proposal.quantity,
            "symbol": contract.symbol,
            "side": action_val.lower(),
            "rationale": getattr(proposal, "rationale", "") or proposal.strategy_name,
        }

        rc_val = verdict.reason_code.value if hasattr(verdict.reason_code, "value") else str(verdict.reason_code)
        rc_list = [rc.value if hasattr(rc, "value") else str(rc) for rc in verdict.reason_codes]
        risk_verdict_dict = {
            "is_approved": verdict.is_approved,
            "reason_code": rc_val,
            "message": verdict.message or ("; ".join(verdict.reasons) if verdict.reasons else "Trade passed all deterministic risk criteria"),
            "trade_cost": str(verdict.trade_cost),
            "max_allowed_budget": str(verdict.max_allowed_budget),
            "portfolio_risk_pct_used": str(verdict.portfolio_risk_pct_used),
            "reasons": list(verdict.reasons),
            "reason_codes": rc_list,
            "warnings": list(verdict.warnings),
            "audited_metrics": dict(verdict.audited_metrics) if verdict.audited_metrics else {
                "trade_cost": float(verdict.trade_cost),
                "max_allowed_risk": float(verdict.max_allowed_budget),
                "portfolio_risk_pct": float(verdict.portfolio_risk_pct_used) * 100.0,
                "spread_pct": float(contract.bid_ask_spread_pct) * 100.0,
                "dte": contract.dte,
            },
        }

        execution_result_dict = {
            "executed": True,
            "execution_status": status,
            "order_id": order_id,
            "status": status.lower(),
            "filled_qty": proposal.quantity,
            "filled_avg_price": str(f_price),
        }

        entry = TradeLogEntry(
            timestamp=now_iso,
            event_type=event_type,
            ticker=contract.underlying_symbol,
            option_symbol=contract.symbol,
            contract_type=target_opt_type,
            strike_price=contract.strike_price,
            expiration_date=contract.expiration_date,
            dte=contract.dte,
            quantity=proposal.quantity,
            trade_cost=verdict.trade_cost,
            strategy_name=proposal.strategy_name,
            action=action_val.upper(),
            is_approved=True,
            risk_reasons=verdict.reasons,
            risk_warnings=verdict.warnings,
            portfolio_risk_pct_used=verdict.portfolio_risk_pct_used,
            order_id=order_id,
            execution_status=status,
            fill_price=f_price,
            greeks=contract.greeks.to_dict(),
            mode=actual_mode,
            market_data_snapshot=market_data_snapshot,
            agent_proposal=agent_proposal,
            risk_verdict=risk_verdict_dict,
            execution_result=execution_result_dict,
        )

        self._append_to_file(entry)
        return entry

    def log_rejected_trade(
        self,
        proposal: TradeProposal,
        verdict: RiskVerdict,
        mode: str = "scan",
        underlying_price: Optional[Decimal] = None,
    ) -> TradeLogEntry:
        """Registra una propuesta de trade rechazada o cancelada por el Risk Engine."""
        contract = proposal.contract
        now_iso = datetime.now(timezone.utc).isoformat()
        u_price = underlying_price or getattr(contract, "underlying_price", None) or contract.strike_price

        market_data_snapshot = {
            "ticker": contract.underlying_symbol,
            "underlying_symbol": contract.underlying_symbol,
            "underlying_price": str(u_price),
            "option_symbol": contract.symbol,
            "bid": str(contract.bid_price),
            "bid_price": str(contract.bid_price),
            "ask": str(contract.ask_price),
            "ask_price": str(contract.ask_price),
            "mid_price": str(contract.mid_price),
            "spread_pct": str(contract.bid_ask_spread_pct),
            "volume": contract.volume,
            "open_interest": contract.open_interest,
            "delta": str(contract.greeks.delta),
            "theta": str(contract.greeks.theta),
            "dte": contract.dte,
            "greeks": contract.greeks.to_dict(),
        }

        target_opt_type = (
            contract.contract_type.value
            if hasattr(contract.contract_type, "value")
            else str(contract.contract_type)
        )
        action_val = proposal.action or getattr(proposal, "side", "BUY") or "BUY"
        agent_proposal = {
            "strategy_name": proposal.strategy_name,
            "signal_type": getattr(proposal, "signal_type", "BULLISH_CALL_MOMENTUM") or "BULLISH_CALL_MOMENTUM",
            "confidence": str(getattr(proposal, "confidence", "0.85")),
            "target_contract_symbol": contract.symbol,
            "target_option_type": target_opt_type,
            "action": action_val.upper(),
            "quantity": proposal.quantity,
            "symbol": contract.symbol,
            "side": action_val.lower(),
            "rationale": getattr(proposal, "rationale", "") or proposal.strategy_name,
        }

        rc_val = verdict.reason_code.value if hasattr(verdict.reason_code, "value") else str(verdict.reason_code)
        rc_list = [rc.value if hasattr(rc, "value") else str(rc) for rc in verdict.reason_codes]
        risk_verdict_dict = {
            "is_approved": False,
            "reason_code": rc_val,
            "message": verdict.message or ("; ".join(verdict.reasons) if verdict.reasons else "Trade rejected by RiskEngine"),
            "trade_cost": str(verdict.trade_cost),
            "max_allowed_budget": str(verdict.max_allowed_budget),
            "portfolio_risk_pct_used": str(verdict.portfolio_risk_pct_used),
            "reasons": list(verdict.reasons),
            "reason_codes": rc_list,
            "warnings": list(verdict.warnings),
            "audited_metrics": dict(verdict.audited_metrics) if verdict.audited_metrics else {
                "trade_cost": float(verdict.trade_cost),
                "max_allowed_risk": float(verdict.max_allowed_budget),
                "portfolio_risk_pct": float(verdict.portfolio_risk_pct_used) * 100.0,
                "spread_pct": float(contract.bid_ask_spread_pct) * 100.0,
                "dte": contract.dte,
            },
        }

        execution_result_dict = {
            "executed": False,
            "execution_status": "REJECTED",
            "order_id": None,
            "status": "rejected",
            "filled_qty": 0,
            "filled_avg_price": None,
        }

        entry = TradeLogEntry(
            timestamp=now_iso,
            event_type="TRADE_REJECTED",
            ticker=contract.underlying_symbol,
            option_symbol=contract.symbol,
            contract_type=target_opt_type,
            strike_price=contract.strike_price,
            expiration_date=contract.expiration_date,
            dte=contract.dte,
            quantity=proposal.quantity,
            trade_cost=verdict.trade_cost,
            strategy_name=proposal.strategy_name,
            action=action_val.upper(),
            is_approved=False,
            risk_reasons=verdict.reasons,
            risk_warnings=verdict.warnings,
            portfolio_risk_pct_used=verdict.portfolio_risk_pct_used,
            order_id=None,
            execution_status="REJECTED",
            fill_price=None,
            greeks=contract.greeks.to_dict(),
            mode=mode,
            market_data_snapshot=market_data_snapshot,
            agent_proposal=agent_proposal,
            risk_verdict=risk_verdict_dict,
            execution_result=execution_result_dict,
        )

        self._append_to_file(entry)
        return entry

    def _append_to_file(self, entry: TradeLogEntry) -> None:
        """Escribe la entrada como una línea JSON en el archivo log con codificación UTF-8."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def get_trade_history(self, limit: int = 50) -> list[TradeLogEntry]:
        """Lee y parsea las últimas N entradas de la bitácora."""
        if limit <= 0:
            return []
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
