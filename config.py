import os
import pytz

# ==========================================
# API Keys & Security
# ==========================================
API_KEY    = os.environ.get("BINANCE_API_KEY", "")
SECRET_KEY = os.environ.get("BINANCE_SECRET", "")
USE_SANDBOX = os.environ.get("USE_SANDBOX", "true").lower() == "true"

# ==========================================
# Trading Symbols
# ==========================================
SYMBOL         = 'BTC/USDT'
TIMEFRAME_EXEC = '15m'
TIMEFRAME_4H   = '4h'
TIMEFRAME_1D   = '1d'
TIMEFRAME_1W   = '1w'

# ==========================================
# Risk Management
# ==========================================
RISK_PER_TRADE    = 0.01   # 1% per trade
MAX_DAILY_LOSS    = -0.02  # -2% daily limit
MAX_DAILY_PROFIT  =  0.04  # +4% daily limit
MIN_RR_RATIO      =  1.5   # Min RR ratio
FEE_RATE          =  0.0004  # 0.04% Binance Futures
LEVERAGE          =  5     # Default leverage
MARGIN_TYPE       = 'ISOLATED'  # ISOLATED or CROSS
MAX_CONSECUTIVE_LOSSES = 3   # Stop after 3 consecutive losses
MAX_DRAWDOWN_PCT  = 0.10   # 10% max drawdown

# ==========================================
# Strategy Settings
# ==========================================
CONFLUENCE_MIN    = 2      # Min confluence score (out of 4)
KILL_ZONE_START   = 7      # NY Kill Zone start hour
KILL_ZONE_END     = 10     # NY Kill Zone end hour
ASIAN_SESSION_CANDLES = 28 # 7 hours (28 × 15m)
LONDON_SESSION_CANDLES = 20  # 5 hours (20 × 15m) — FIXED

# ==========================================
# Fibonacci Settings
# ==========================================
FIB_OTE_LOW    = 0.618
FIB_OTE_MID    = 0.705
FIB_OTE_HIGH   = 0.79
FIB_CE         = 0.50

# ==========================================
# Partial TP Settings
# ==========================================
TP1_PCT    = 0.50   # Close 50% at TP1
TP2_PCT    = 0.30   # Close 30% at TP2
TP3_PCT    = 0.20   # Close 20% at TP3

# ==========================================
# Timezone
# ==========================================
NY_TZ = pytz.timezone('America/New_York')

# ==========================================
# Logging
# ==========================================
LOG_MAX_LINES = 200
LOG_FILE      = "trade_journal.json"

# ==========================================
# Telegram Alerts (optional)
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ==========================================
# Validation
# ==========================================
if not API_KEY or not SECRET_KEY:
    print("⚠️ WARNING: BINANCE_API_KEY or BINANCE_SECRET not set!")
