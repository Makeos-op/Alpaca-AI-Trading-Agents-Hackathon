"""
Pruebas Unitarias para Feature 4: Motor de Opciones y Análisis Cuantitativo con Decimal (FT-OPT-04).
"""

import unittest
from decimal import Decimal
from types import SimpleNamespace

from src.options.chain_filter import (
    filter_by_contract_type,
    filter_option_chain,
    find_atm_contract,
    find_target_delta_contract,
)
from src.options.greeks import (
    classify_iv_regime,
    classify_moneyness,
    parse_alpaca_greeks,
)
from src.options.models import (
    IVRegime,
    Moneyness,
    OptionContract,
    OptionGreeks,
    OptionType,
)


class TestOptionContractModel(unittest.TestCase):
    """Pruebas de modelado de contratos de opciones y precisión Decimal."""

    def test_option_contract_creation_spy_example(self):
        contract = OptionContract.create(
            symbol="SPY260930C00500000",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500.00",
            expiration_date="2026-09-30",
            dte=30,
            bid_price="2.10",
            ask_price="2.20",
            volume=2340,
            open_interest=1870,
            delta="0.45",
            gamma="0.08",
            theta="-0.04",
            vega="0.12",
            implied_volatility="0.1850",
            moneyness=Moneyness.ATM,
        )

        self.assertEqual(contract.symbol, "SPY260930C00500000")
        self.assertEqual(contract.strike_price, Decimal("500.00"))
        self.assertEqual(contract.bid_price, Decimal("2.10"))
        self.assertEqual(contract.ask_price, Decimal("2.20"))
        self.assertEqual(contract.mid_price, Decimal("2.15"))
        self.assertEqual(contract.bid_ask_spread_pct, Decimal("0.0465"))
        self.assertEqual(contract.greeks.delta, Decimal("0.45"))
        self.assertEqual(contract.greeks.theta, Decimal("-0.04"))
        self.assertEqual(contract.greeks.implied_volatility, Decimal("0.1850"))

    def test_calculate_trade_cost(self):
        contract = OptionContract.create(
            symbol="AAPL260930C00180000",
            underlying_symbol="AAPL",
            contract_type=OptionType.CALL,
            strike_price="180.00",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="3.00",
            ask_price="3.20",
        )

        cost_1 = contract.calculate_trade_cost(contracts=1, use_ask=True)
        self.assertEqual(cost_1, Decimal("320.00"))

        cost_3 = contract.calculate_trade_cost(contracts=3, use_ask=True)
        self.assertEqual(cost_3, Decimal("960.00"))

        cost_mid = contract.calculate_trade_cost(contracts=2, use_ask=False)
        self.assertEqual(cost_mid, Decimal("620.00"))

    def test_to_dict_serialization(self):
        contract = OptionContract.create(
            symbol="TEST",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500",
            expiration_date="2026-09-30",
            dte=15,
            bid_price="2.00",
            ask_price="2.10",
        )
        data = contract.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["symbol"], "TEST")
        self.assertEqual(data["contract_type"], "CALL")
        self.assertIsInstance(data["strike_price"], str)


class TestGreeksAndMoneyness(unittest.TestCase):
    """Pruebas de clasificación de Moneyness, régimen IV y parsing de griegas."""

    def test_classify_moneyness_call_by_delta(self):
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("500"), Decimal("500"), Decimal("0.50")),
            Moneyness.ATM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("480"), Decimal("500"), Decimal("0.75")),
            Moneyness.ITM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("520"), Decimal("500"), Decimal("0.25")),
            Moneyness.OTM,
        )

    def test_classify_moneyness_put_by_delta(self):
        self.assertEqual(
            classify_moneyness(OptionType.PUT, Decimal("500"), Decimal("500"), Decimal("-0.50")),
            Moneyness.ATM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.PUT, Decimal("520"), Decimal("500"), Decimal("-0.75")),
            Moneyness.ITM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.PUT, Decimal("480"), Decimal("500"), Decimal("-0.25")),
            Moneyness.OTM,
        )

    def test_classify_moneyness_by_price_proximity(self):
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("101"), Decimal("100")),
            Moneyness.ATM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("110"), Decimal("100")),
            Moneyness.OTM,
        )
        self.assertEqual(
            classify_moneyness(OptionType.CALL, Decimal("90"), Decimal("100")),
            Moneyness.ITM,
        )

    def test_classify_iv_regime(self):
        self.assertEqual(classify_iv_regime(Decimal("0.15")), IVRegime.LOW)
        self.assertEqual(classify_iv_regime(Decimal("0.25")), IVRegime.MODERATE)
        self.assertEqual(classify_iv_regime(Decimal("0.40")), IVRegime.MODERATE)
        self.assertEqual(classify_iv_regime(Decimal("0.55")), IVRegime.HIGH)

    def test_parse_alpaca_greeks_from_dict_and_object(self):
        g_dict = {"delta": 0.45, "gamma": 0.08, "theta": -0.04, "vega": 0.12, "iv": 0.185}
        parsed = parse_alpaca_greeks(g_dict)
        self.assertEqual(parsed.delta, Decimal("0.45"))
        self.assertEqual(parsed.implied_volatility, Decimal("0.185"))

        g_obj = SimpleNamespace(delta=0.30, gamma=0.05, theta=-0.02, vega=0.10, implied_volatility=0.22)
        parsed_obj = parse_alpaca_greeks(g_obj)
        self.assertEqual(parsed_obj.delta, Decimal("0.30"))
        self.assertEqual(parsed_obj.implied_volatility, Decimal("0.22"))


class TestChainFilter(unittest.TestCase):
    """Pruebas de filtrado cuantitativo de cadenas de opciones."""

    def _sample_contracts(self):
        c1 = OptionContract.create(
            symbol="CALL_PERFECT",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.10",
            ask_price="2.20",
            open_interest=1000,
            delta="0.50",
        )
        c2 = OptionContract.create(
            symbol="CALL_0DTE",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="500",
            expiration_date="2026-09-02",
            dte=0,
            bid_price="1.00",
            ask_price="1.05",
            open_interest=1000,
            delta="0.50",
        )
        c3 = OptionContract.create(
            symbol="CALL_LOW_OI",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="505",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="1.50",
            ask_price="1.55",
            open_interest=100,
            delta="0.40",
        )
        c4 = OptionContract.create(
            symbol="CALL_WIDE_SPREAD",
            underlying_symbol="SPY",
            contract_type=OptionType.CALL,
            strike_price="510",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="1.00",
            ask_price="1.30",
            open_interest=1000,
            delta="0.30",
        )
        c5 = OptionContract.create(
            symbol="PUT_TARGET_DELTA",
            underlying_symbol="SPY",
            contract_type=OptionType.PUT,
            strike_price="490",
            expiration_date="2026-09-30",
            dte=20,
            bid_price="2.00",
            ask_price="2.08",
            open_interest=1500,
            delta="-0.30",
        )
        return [c1, c2, c3, c4, c5]

    def test_filter_option_chain_removes_invalid_contracts(self):
        contracts = self._sample_contracts()
        filtered = filter_option_chain(contracts, min_dte=1, max_dte=30, min_open_interest=500, max_spread_pct=Decimal("0.05"))
        
        self.assertEqual(len(filtered), 2)
        symbols = [c.symbol for c in filtered]
        self.assertIn("CALL_PERFECT", symbols)
        self.assertIn("PUT_TARGET_DELTA", symbols)
        self.assertNotIn("CALL_0DTE", symbols)
        self.assertNotIn("CALL_LOW_OI", symbols)
        self.assertNotIn("CALL_WIDE_SPREAD", symbols)

    def test_find_atm_contract(self):
        contracts = self._sample_contracts()
        atm_call = find_atm_contract(contracts, OptionType.CALL, underlying_price=Decimal("499.50"))
        self.assertIsNotNone(atm_call)
        self.assertEqual(atm_call.strike_price, Decimal("500"))

    def test_find_target_delta_contract(self):
        contracts = self._sample_contracts()
        put = find_target_delta_contract(contracts, OptionType.PUT, target_delta=Decimal("-0.30"))
        self.assertIsNotNone(put)
        self.assertEqual(put.symbol, "PUT_TARGET_DELTA")


if __name__ == "__main__":
    unittest.main()

