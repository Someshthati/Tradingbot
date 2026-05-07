import os
import time
import threading
from dotenv import load_dotenv
import pytz
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
from flask import Flask

# Alpaca Imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

load_dotenv()
# --- 1. CONFIGURATION ---
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
# Top tickers to scan
TICKERS = ["META", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "GOOGL", "AMZN", "NFLX", "COIN", "TSM", "ARM", "GS", "QQQ", "SPY"] # Add up to 25
RISK_PER_TRADE = 1000 # Dollars to spend per trade

# Initialize Clients
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. WEB SERVER SETUP (For Render Free Tier) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Agent is Online. Use UptimeRobot to ping this URL every 10 mins.", 200

@app.route('/healthz')
def health():
    return "OK", 200

# --- 3. TRADING LOGIC ---
def is_market_open():
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() >= 5: return False
    opening = now.replace(hour=9, minute=30, second=0, microsecond=0)
    closing = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return opening <= now <= closing

def get_signals():
    request_params = StockBarsRequest(
        symbol_or_symbols=TICKERS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        start=datetime.now() - timedelta(days=5),
        feed="iex" # Crucial for free Alpaca tier
    )
    
    try:
        bars_response = data_client.get_stock_bars(request_params)
        bars = bars_response.df
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return []

    signals = []
    for ticker in TICKERS:
        try:
            # Slice data for the specific ticker
            df = bars.loc[ticker].copy()
            df['ema9'] = ta.ema(df['close'], length=9)
            df['ema20'] = ta.ema(df['close'], length=20)
            
            if len(df) < 2: continue
            
            curr, prev = df.iloc[-1], df.iloc[-2]
            
            # The "Bear Trap" logic
            sweep = prev['low'] < prev['ema20']
            reclaim = curr['close'] > curr['ema9']
            
            if sweep and reclaim:
                signals.append({
                    'ticker': ticker, 
                    'price': curr['close'], 
                    'stop': prev['low']
                })
        except Exception:
            continue
    return signals

def execute_trade(signal):
    ticker = signal['ticker']
    
    # Check if we already have a position
    positions = [p.symbol for p in trading_client.get_all_positions()]
    if ticker in positions:
        return

    qty = int(RISK_PER_TRADE / signal['price'])
    if qty < 1: return

    try:
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
        print(f"✅ Trade Executed for {ticker}")
    except Exception as e:
        print(f"Order failed for {ticker}: {e}")

# --- 4. BACKGROUND BOT THREAD ---
def run_trading_loop():
    print("Bot loop started in background...")
    while True:
        try:
            if is_market_open():
                print(f"[{datetime.now()}] Scanning for signals...")
                signals = get_signals()
                for sig in signals:
                    execute_trade(sig)
            else:
                # To see output in Render logs while closed
                print("Market is currently closed.")
            
            # Wait 60 seconds before next scan
            time.sleep(60)
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            time.sleep(30)

# --- 5. ENTRY POINT ---
if __name__ == "__main__":
    # Start the bot in its own thread
    t = threading.Thread(target=run_trading_loop)
    t.daemon = True
    t.start()
    
    # Start Flask (Render uses the PORT environment variable)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)