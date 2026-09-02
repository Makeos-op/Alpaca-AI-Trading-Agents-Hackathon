import os
from decimal import Decimal

from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

load_dotenv()
trading_client = TradingClient(os.getenv("API_KEY"),os.getenv("SECRET_KEY"),paper = True)  

def get_account_snapshot():
    tc_info = trading_client.get_account()
    account_snapshot = {
        "account_id": tc_info.account_id,
        "cash": Decimal(tc_info.cash),
        "portfolio_value": Decimal(tc_info.portfolio_value),
        "buying_power": Decimal(tc_info.buying_power),
        "equity": Decimal(tc_info.equity),
        "long_market_value": Decimal(tc_info.long_market_value),
        "short_market_value": Decimal(tc_info.short_market_value),
        "initial_margin": Decimal(tc_info.initial_margin),
        "maintenance_margin": Decimal(tc_info.maintenance_margin),
        "daytrading_buying_power": Decimal(tc_info.daytrading_buying_power),
        "daytrading_count": tc_info.daytrading_count,
        "is_daytrader": tc_info.is_daytrader,
        "is_active": tc_info.is_active,
        "is_frozen": tc_info.is_frozen,
    }
    return account_snapshot


