"""
Motor de Filtrado y Selección de Cadenas de Opciones (Feature 4: FT-OPT-04).
Aplica filtros cuantitativos de DTE (1-30 días), Open Interest (>= 500) y Spread (<= 5%).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from src.config import (
    MAX_DTE,
    MAX_OPTION_SPREAD_PCT,
    MIN_DTE,
    MIN_OPTION_OPEN_INTEREST,
)
from src.options.models import OptionContract, OptionType


def filter_option_chain(
    contracts: list[OptionContract],
    min_dte: int = MIN_DTE,
    max_dte: int = MAX_DTE,
    min_open_interest: int = MIN_OPTION_OPEN_INTEREST,
    max_spread_pct: Decimal = MAX_OPTION_SPREAD_PCT,
) -> list[OptionContract]:
    """Filtra la cadena de opciones según las reglas cuantitativas."""
    valid_contracts: list[OptionContract] = []

    for contract in contracts:
        if contract.dte < min_dte or contract.dte > max_dte:
            continue

        if contract.open_interest < min_open_interest:
            continue

        if contract.bid_ask_spread_pct > max_spread_pct:
            continue

        if contract.bid_price <= Decimal("0.0") or contract.ask_price <= Decimal("0.0"):
            continue

        valid_contracts.append(contract)

    return valid_contracts


def filter_by_contract_type(
    contracts: list[OptionContract],
    contract_type: OptionType,
) -> list[OptionContract]:
    """Filtra una lista de contratos por tipo (CALL o PUT)."""
    return [c for c in contracts if c.contract_type == contract_type]


def find_atm_contract(
    contracts: list[OptionContract],
    contract_type: OptionType,
    underlying_price: Decimal,
) -> Optional[OptionContract]:
    """Encuentra el contrato más cercano a At-The-Money (ATM)."""
    typed_contracts = filter_by_contract_type(contracts, contract_type)
    if not typed_contracts:
        return None

    return min(typed_contracts, key=lambda c: abs(c.strike_price - underlying_price))


def find_target_delta_contract(
    contracts: list[OptionContract],
    contract_type: OptionType,
    target_delta: Decimal,
) -> Optional[OptionContract]:
    """Encuentra el contrato con el Delta más cercano al objetivo."""
    typed_contracts = filter_by_contract_type(contracts, contract_type)
    if not typed_contracts:
        return None

    return min(typed_contracts, key=lambda c: abs(c.greeks.delta - target_delta))

