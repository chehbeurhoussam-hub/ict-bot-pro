import urllib.request
import json
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from state_logger import log

# ==========================================
# Telegram Alert System (NEW)
# ==========================================

def send_telegram(message: str, parse_mode: str = 'HTML'):
    """Send Telegram alert"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get('ok'):
                log("📨 Telegram sent")
                return True
            else:
                log(f"⚠️ Telegram error: {result}")
                return False

    except Exception as e:
        log(f"⚠️ Telegram failed: {e}")
        return False

def alert_trade_opened(signal: str, entry: float, sl: float, tp: float, rr: float, confluence: int):
    """Alert when trade is opened"""
    emoji = '🟢' if signal == 'BUY' else '🔴'
    message = f"""
{emoji} <b>NEW TRADE OPENED</b> {emoji}

📊 <b>Signal:</b> {signal}
💰 <b>Entry:</b> {entry:.2f}
🛑 <b>SL:</b> {sl:.2f}
🎯 <b>TP:</b> {tp:.2f}
📐 <b>RR:</b> 1:{rr:.2f}
⭐ <b>Confluence:</b> {confluence}/4

Good luck! 🍀
"""
    send_telegram(message)

def alert_trade_closed(signal: str, entry: float, exit_price: float, pnl: float, result: str):
    """Alert when trade is closed"""
    emoji = '✅' if result == 'WIN' else '❌'
    pnl_emoji = '📈' if pnl > 0 else '📉'
    message = f"""
{emoji} <b>TRADE CLOSED</b> {emoji}

📊 <b>Signal:</b> {signal}
💰 <b>Entry:</b> {entry:.2f}
🏁 <b>Exit:</b> {exit_price:.2f}
{pnl_emoji} <b>PnL:</b> {pnl:.2f}R
<b>Result:</b> {result}
"""
    send_telegram(message)

def alert_daily_limit(pnl_pct: float, limit_type: str):
    """Alert when daily limit is hit"""
    emoji = '🛑' if limit_type == 'loss' else '🎯'
    message = f"""
{emoji} <b>DAILY LIMIT HIT</b> {emoji}

📊 <b>Type:</b> {limit_type.upper()}
📉 <b>PnL:</b> {pnl_pct*100:.2f}%

Trading stopped for today. See you tomorrow! 👋
"""
    send_telegram(message)

def alert_emergency_stop(reason: str):
    """Alert on emergency stop"""
    message = f"""
🚨🚨🚨 <b>EMERGENCY STOP</b> 🚨🚨🚨

<b>Reason:</b> {reason}

All positions closed. Manual intervention required!
"""
    send_telegram(message)

def alert_error(error_msg: str):
    """Alert on critical error"""
    message = f"""
⚠️ <b>CRITICAL ERROR</b> ⚠️

<code>{error_msg}</code>

Please check the bot immediately!
"""
    send_telegram(message)

def alert_daily_summary(trades: int, wins: int, losses: int, pnl: float):
    """Daily summary report"""
    win_rate = (wins / trades * 100) if trades > 0 else 0
    emoji = '📈' if pnl > 0 else '📉'
    message = f"""
📊 <b>DAILY SUMMARY</b> 📊

📈 <b>Trades:</b> {trades}
✅ <b>Wins:</b> {wins}
❌ <b>Losses:</b> {losses}
🎯 <b>Win Rate:</b> {win_rate:.1f}%
{emoji} <b>Total PnL:</b> {pnl:.2f}R

See you tomorrow! 🌙
"""
    send_telegram(message)
