"""
Pruebas Unitarias para Feature 3: Screener e Indicadores Técnicos con Decimal (FT-MKT-03).
"""

import unittest
from decimal import Decimal
from types import SimpleNamespace

from src.data.market import MarketDataService, screen_ticker_liquidity
from src.indicators.technicals import (
    MACDResult,
    PriceBar,
    TechnicalSnapshot,
    calculate_52w_high_low,
    calculate_atr,
    calculate_daily_return,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    compute_technical_snapshot,
    to_decimal,
)


class TestTechnicalsWithDecimal(unittest.TestCase):
    """Pruebas del motor matemático de indicadores usando aritmética Decimal estricta."""

    def test_to_decimal_safety(self):
        self.assertEqual(to_decimal("150.25"), Decimal("150.25"))
        self.assertEqual(to_decimal(150), Decimal("150"))
        self.assertEqual(to_decimal(None), Decimal("0.0"))
        self.assertEqual(to_decimal("invalid", "10.0"), Decimal("10.0"))

    def test_sma_exact_decimal(self):
        prices = [Decimal("100.00"), Decimal("102.50"), Decimal("105.00"), Decimal("107.50")]
        sma_4 = calculate_sma(prices, 4)
        self.assertEqual(sma_4, Decimal("103.7500"))

    def test_sma_insufficient_data(self):
        prices = [Decimal("100.00"), Decimal("102.00")]
        self.assertIsNone(calculate_sma(prices, 5))
        self.assertIsNone(calculate_sma(prices, 0))

    def test_ema_exact_decimal(self):
        prices = [
            Decimal("10.00"), Decimal("11.00"), Decimal("12.00"),
            Decimal("13.00"), Decimal("14.00"), Decimal("15.00"),
        ]
        ema = calculate_ema(prices, 3)
        self.assertEqual(len(ema), 4)
        self.assertEqual(ema[0], Decimal("11.000000"))
        self.assertEqual(ema[1], Decimal("12.000000"))
        self.assertEqual(ema[2], Decimal("13.000000"))
        self.assertEqual(ema[3], Decimal("14.000000"))

    def test_rsi_all_gains_equals_100(self):
        prices = [Decimal(str(100 + i * 2)) for i in range(20)]
        rsi = calculate_rsi(prices, period=14)
        self.assertIsNotNone(rsi)
        self.assertEqual(rsi, Decimal("100.0000"))

    def test_rsi_all_losses_equals_0(self):
        prices = [Decimal(str(200 - i * 2)) for i in range(20)]
        rsi = calculate_rsi(prices, period=14)
        self.assertIsNotNone(rsi)
        self.assertEqual(rsi, Decimal("0.0000"))

    def test_rsi_standard_oscillation(self):
        prices = [
            Decimal("100.0"), Decimal("102.0"), Decimal("101.0"), Decimal("103.0"),
            Decimal("105.0"), Decimal("104.0"), Decimal("106.0"), Decimal("108.0"),
            Decimal("107.0"), Decimal("109.0"), Decimal("111.0"), Decimal("110.0"),
            Decimal("112.0"), Decimal("114.0"), Decimal("113.0"), Decimal("115.0"),
        ]
        rsi = calculate_rsi(prices, period=14)
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, Decimal("50.0"))
        self.assertLessEqual(rsi, Decimal("100.0"))

    def test_macd_calculation_and_histogram_consistency(self):
        prices = [Decimal(str(100 + (i % 7) * 2 + i)) for i in range(40)]
        macd = calculate_macd(prices, fast=12, slow=26, signal=9)
        self.assertIsNotNone(macd)
        self.assertIsInstance(macd.macd_line, Decimal)
        self.assertIsInstance(macd.signal_line, Decimal)
        self.assertIsInstance(macd.histogram, Decimal)
        expected_diff = macd.macd_line - macd.signal_line
        self.assertEqual(macd.histogram, expected_diff)

    def test_atr_calculation(self):
        bars = []
        for i in range(20):
            base = Decimal(str(100 + i))
            bars.append(
                PriceBar.create(
                    open_p=base,
                    high_p=base + Decimal("5.0"),
                    low_p=base - Decimal("2.0"),
                    close_p=base + Decimal("3.0"),
                    volume_p="1500000",
                )
            )
        atr = calculate_atr(bars, period=14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, Decimal("0.0"))
        self.assertIsInstance(atr, Decimal)

    def test_daily_return_and_52w_high_low(self):
        b1 = PriceBar.create(open_p=100, high_p=105, low_p=98, close_p=100, volume_p=1000)
        b2 = PriceBar.create(open_p=101, high_p=110, low_p=99, close_p=105, volume_p=2000)
        bars = [b1, b2]

        ret = calculate_daily_return(bars)
        self.assertEqual(ret, Decimal("5.0000"))

        high_52, low_52 = calculate_52w_high_low(bars)
        self.assertEqual(high_52, Decimal("110.0"))
        self.assertEqual(low_52, Decimal("98.0"))

    def test_compute_technical_snapshot_bullish(self):
        bars = []
        for i in range(60):
            val = Decimal(str(100 + i * 2))
            bars.append(
                PriceBar.create(
                    open_p=val,
                    high_p=val + Decimal("1.0"),
                    low_p=val - Decimal("1.0"),
                    close_p=val,
                    volume_p="2000000",
                )
            )
        snapshot = compute_technical_snapshot("AAPL", bars)
        self.assertEqual(snapshot.ticker, "AAPL")
        self.assertEqual(snapshot.trend_summary, "BULLISH")
        self.assertEqual(snapshot.rsi_condition, "OVERBOUGHT")
        
        d = snapshot.to_dict()
        self.assertEqual(d["ticker"], "AAPL")
        self.assertIsInstance(d["current_price"], str)


class TestLiquidityScreener(unittest.TestCase):
    """Pruebas del screener de liquidez y calificación por estrellas."""

    def test_liquidity_screener_5_stars(self):
        score = screen_ticker_liquidity(
            ticker="AAPL",
            daily_volume="50000000",
            bid_price="175.20",
            ask_price="175.40",
            option_open_interest=1200,
        )
        self.assertTrue(score.is_tradable)
        self.assertEqual(score.stars, 5)
        self.assertEqual(len(score.reasons), 0)
        self.assertLess(score.bid_ask_spread_pct, Decimal("0.01"))

    def test_liquidity_screener_insufficient_volume(self):
        score = screen_ticker_liquidity(
            ticker="ILLIQ",
            daily_volume="500000",
            bid_price="50.00",
            ask_price="50.10",
            option_open_interest=800,
        )
        self.assertFalse(score.is_tradable)
        self.assertTrue(any("Volumen insuficiente" in r for r in score.reasons))

    def test_liquidity_screener_wide_spread(self):
        score = screen_ticker_liquidity(
            ticker="WIDE",
            daily_volume="2000000",
            bid_price="10.00",
            ask_price="11.00",
            option_open_interest=800,
        )
        self.assertFalse(score.is_tradable)
        self.assertTrue(any("Spread excesivo" in r for r in score.reasons))

    def test_liquidity_screener_low_open_interest(self):
        score = screen_ticker_liquidity(
            ticker="LOWOI",
            daily_volume="2000000",
            bid_price="100.00",
            ask_price="100.20",
            option_open_interest=100,
        )
        self.assertFalse(score.is_tradable)
        self.assertTrue(any("Open Interest" in r for r in score.reasons))

    def test_market_data_service_parse_bars(self):
        service = MarketDataService()
        raw_bars = [
            SimpleNamespace(open=150.0, high=155.0, low=149.0, close=154.0, volume=1000000, timestamp="2026-09-01"),
            SimpleNamespace(open=154.0, high=158.0, low=153.0, close=157.0, volume=1200000, timestamp="2026-09-02"),
        ]
        parsed = service.parse_alpaca_bars(raw_bars)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].close, Decimal("154.0"))
        self.assertEqual(parsed[1].volume, Decimal("1200000"))


if __name__ == "__main__":
    unittest.main()

