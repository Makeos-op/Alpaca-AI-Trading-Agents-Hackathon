from alpaca.trading.client import TradingClient
from decimal import Decimal
from dotenv import load_dotenv
import os

load_dotenv()
trading_client = TradingClient(os.getenv("API_KEY"),os.getenv("SECRET_KEY"),paper = True)  

def get_account_snapshot(){
    tc_info= trading_client.get_account()
    
}

