import time
from dotenv import load_dotenv
import pytz
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import os
load_dotenv()   
# --- 1. CONFIGURATION ---
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
TICKERS = ["META", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "GOOGL", "AMZN", "NFLX", "COIN", "TSM", "ARM", "GS", "QQQ", "SPY"] # Add up to 25
RISK_PER_TRADE = 1000 # Dollars to spend per trade

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

def is_market_open():
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() >= 5: return False
    opening = now.replace(hour=9, minute=30, second=0)
    closing = now.replace(hour=16, minute=0, second=0)
    return opening <= now <= closing

def get_signals():
    # Fetch 15-min bars for all tickers at once
    request_params = StockBarsRequest(
        symbol_or_symbols=TICKERS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        start=datetime.now() - timedelta(days=5),
        feed="iex"
    )
    
    try:
        bars = data_client.get_stock_bars(request_params).df
    except Exception as e:
        print(f"Data Error: {e}")
        return []

    signals = []
    for ticker in TICKERS:
        try:
            df = bars.loc[ticker].copy()
            df['ema9'] = ta.ema(df['close'], length=9)
            df['ema20'] = ta.ema(df['close'], length=20)
            
            if len(df) < 2: continue
            
            curr, prev = df.iloc[-1], df.iloc[-2]
            
            # THE LOGIC: Dip below 20 EMA, then close above 9 EMA
            sweep = prev['low'] < prev['ema20']
            reclaim = curr['close'] > curr['ema9']
            
            if sweep and reclaim:
                signals.append({
                    'ticker': ticker,
                    'price': curr['close'],
                    'stop': prev['low']
                })
        except KeyError:
            continue
    return signals

def execute_trade(signal):
    ticker = signal['ticker']
    
    # 1. Avoid duplicate trades
    positions = [p.symbol for p in trading_client.get_all_positions()]
    if ticker in positions:
        print(f"Skipping {ticker}: Position already open.")
        return

    # 2. Calculate quantity based on risk
    qty = int(RISK_PER_TRADE / signal['price'])
    if qty < 1: return

    # 3. Create Bracket Order
    print(f"🚀 TRAP DETECTED: Buying {qty} shares of {ticker}...")
    
    order_data = MarketOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(signal['price'] * 1.02, 2)),
        stop_loss=StopLossRequest(stop_price=round(signal['stop'], 2))
    )
    
    trading_client.submit_order(order_data)

# --- 2. MAIN LOOP ---
print("Agent Online. Monitoring for Bear Traps...")

while True:
    if is_market_open():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning Top Tickers...")
        current_signals = get_signals()
        
        for sig in current_signals:
            execute_trade(sig)
            
        time.sleep(60) # Wait for the next minute
    else:
        # Sleep until the next check if market is closed
        print("Market Closed. Checking again in 5 minutes...")
        time.sleep(300)