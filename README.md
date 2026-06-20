# 🎯 القناص الذكي — ICT Trading Bot Pro

## نظرة عامة

بوت تداول متكامل بناءً على استراتيجية **ICT (Inner Circle Trader)** مع إدارة مخاطر متقدمة ومراقبة حية.

## ✨ المميزات الجديدة

### 🔴 إدارة المخاطر المتقدمة
- ✅ Leverage Management (5x افتراضي)
- ✅ Liquidation Price Monitoring
- ✅ Circuit Breaker (Daily Loss + Consecutive Losses + Max Drawdown)
- ✅ Volatility-Based Position Sizing
- ✅ Margin Type Control (ISOLATED/CROSS)

### 🔴 تنفيذ متقدم
- ✅ Order Validation قبل الإرسال
- ✅ Order Tracking (Entry/SL/TP IDs)
- ✅ Bracket Order Logic
- ✅ Partial Fill Handling
- ✅ Cancel Old Orders safely

### 🔴 استراتيجية ICT محسّنة
- ✅ BOS/CHoCH Detection
- ✅ Liquidity Sweep Detection
- ✅ Market Regime Detection (Trending/Range)
- ✅ EMA Fixed (يبدأ من الأحدث)
- ✅ AMD Fixed (أول كسر يحدد الاتجاه)
- ✅ MSS Fixed (3 شمعات متتالية)

### 🔴 مراقبة وتنبيهات
- ✅ Telegram Alerts (Trade Opened/Closed/Daily Limit/Emergency)
- ✅ Emergency Stop Button
- ✅ Real-time Dashboard
- ✅ Equity Curve & Drawdown Charts

### 🔴 أمان
- ✅ Audit Logging
- ✅ API Key Validation
- ✅ Sandbox/Production Mode
- ✅ Docker Containerization

### 🔴 اختبار
- ✅ Unit Tests
- ✅ Realistic Backtest (BOS/CHoCH + Liquidity Sweep)
- ✅ Monthly Breakdown
- ✅ Profit Factor

## 🚀 التشغيل

### 1. Docker (موصى به)
```bash
cp .env.example .env
# عدل .env بمفاتيحك
docker-compose up -d
```

### 2. Systemd
```bash
sudo cp ict-bot.service /etc/systemd/system/
sudo systemctl enable ict-bot
sudo systemctl start ict-bot
```

### 3. Manual
```bash
pip install -r requirements.txt
python app.py
```

## 📋 المتطلبات

- Python 3.11+
- Binance Futures API Keys
- (اختياري) Telegram Bot Token

## 🧪 الاختبار

```bash
python -m pytest tests/ -v
```

## ⚠️ تحذير

هذا بوت تداول حقيقي. استخدم **Sandbox Mode** أولاً!
```
USE_SANDBOX=true
```

## 📄 الملفات المُعدّلة

| الملف | التغييرات |
|-------|----------|
| config.py | +LEVERAGE, +MARGIN_TYPE, +MAX_CONSECUTIVE_LOSSES, +MAX_DRAWDOWN, +TELEGRAM |
| state_logger.py | Thread-safe, Atomic writes, Audit logging |
| risk_manager.py | Leverage, Liquidation check, Volatility sizing, Consecutive losses |
| ict_engine.py | Fixed EMA, Fixed AMD, BOS/CHoCH, Liquidity Sweep, Market Regime |
| executor.py | Order validation, Order tracking, Bracket logic, Retry logic |
| core.py | Retry decorator, Regime filter, BOS/CHoCH, Liquidity Sweep, BE check |
| backtester.py | Realistic simulation, Monthly stats, Profit Factor |
| news_filter.py | Fixed timezone, Smart fallback |
| app.py | Emergency stop, Charts, Enhanced stats |
| telegram_alerts.py | NEW — Trade/Daily/Emergency alerts |
| tests/ | NEW — Unit tests for all components |
| Dockerfile | NEW |
| docker-compose.yml | NEW |
| ict-bot.service | NEW |

## 📞 الدعم

للأسئلة أو المشاكل، افتح Issue في المستودع.
