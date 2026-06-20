import json
import os
from datetime import datetime, timedelta
from config import (
    RISK_PER_TRADE, MAX_DAILY_LOSS, MAX_DAILY_PROFIT,
    MIN_RR_RATIO, FEE_RATE, NY_TZ, LEVERAGE, MARGIN_TYPE,
    MAX_CONSECUTIVE_LOSSES, MAX_DRAWDOWN_PCT
)
from state_logger import log, audit_log

# ==========================================
# Daily Balance Tracker
# ==========================================
_start_balance_file = "start_balance.json"
_consecutive_losses_file = "consecutive_losses.json"

def get_start_balance(current_balance: float) -> float:
    today = datetime.now(NY_TZ).strftime('%Y-%m-%d')

    if os.path.exists(_start_balance_file):
        try:
            with open(_start_balance_file, 'r') as f:
                data = json.load(f)
            if data.get('date') == today:
                return data['balance']
        except Exception as e:
            log(f"⚠️ خطأ قراءة start_balance: {e}")

    # New day — save current balance
    try:
        with open(_start_balance_file, 'w') as f:
            json.dump({'date': today, 'balance': current_balance}, f)
    except Exception as e:
        log(f"⚠️ خطأ حفظ start_balance: {e}")

    log(f"📅 رصيد بداية اليوم: {current_balance:.2f} USDT")
    return current_balance

def check_daily_pnl(exchange) -> tuple[bool, str]:
    try:
        # Get free + used balance (realized, not including unrealized)
        balance_data = exchange.fetch_balance()
        bal = float(balance_data['free']['USDT']) + float(balance_data['used']['USDT'])
        start = get_start_balance(bal)
        pnl_pct = (bal - start) / start if start > 0 else 0

        status = f"💰 Balance: {bal:.2f} | PnL: {pnl_pct*100:.2f}%"

        # Check daily loss limit
        if pnl_pct <= MAX_DAILY_LOSS:
            log(f"🛑 Daily Loss {pnl_pct*100:.2f}% — حد الخسارة")
            audit_log('DAILY_LIMIT_HIT', {'type': 'loss', 'pnl_pct': pnl_pct})
            return False, status

        # Check daily profit limit
        if pnl_pct >= MAX_DAILY_PROFIT:
            log(f"🎯 Daily Profit {pnl_pct*100:.2f}% — حد الربح")
            audit_log('DAILY_LIMIT_HIT', {'type': 'profit', 'pnl_pct': pnl_pct})
            return False, status

        # Check max drawdown
        journal_file = "trade_journal.json"
        if os.path.exists(journal_file):
            try:
                with open(journal_file, 'r') as f:
                    trades = json.load(f)
                closed = [t for t in trades if t.get('result') in ('WIN', 'LOSS', 'BE')]
                equity = 0
                peak = 0
                max_dd = 0
                for t in closed:
                    pnl = t.get('pnl_pct', 0)
                    if isinstance(pnl, str):
                        try:
                            pnl = float(pnl)
                        except:
                            pnl = 0
                    equity += pnl
                    if equity > peak:
                        peak = equity
                    dd = peak - equity
                    if dd > max_dd:
                        max_dd = dd
                if max_dd >= MAX_DRAWDOWN_PCT:
                    log(f"🛑 Max Drawdown {max_dd*100:.1f}% — إيقاف تلقائي")
                    audit_log('MAX_DRAWDOWN_HIT', {'drawdown': max_dd})
                    return False, status
            except Exception as e:
                log(f"⚠️ خطأ حساب Drawdown: {e}")

        # Check consecutive losses
        consecutive = _get_consecutive_losses()
        if consecutive >= MAX_CONSECUTIVE_LOSSES:
            log(f"🛑 {consecutive} خسائر متتالية — توقف مؤقت")
            audit_log('CONSECUTIVE_LOSSES', {'count': consecutive})
            return False, status

        log(status)
        return True, status

    except Exception as e:
        log(f"⚠️ خطأ PnL: {e}")
        return True, "⚠️ تعذر حساب PnL"

def _get_consecutive_losses() -> int:
    """عدد الخسائر المتتالية من الجورنال"""
    if not os.path.exists("trade_journal.json"):
        return 0
    try:
        with open("trade_journal.json", 'r') as f:
            trades = json.load(f)
        closed = [t for t in trades if t.get('result') in ('WIN', 'LOSS', 'BE')]
        count = 0
        for t in reversed(closed):
            if t.get('result') == 'LOSS':
                count += 1
            else:
                break
        return count
    except:
        return 0

# ==========================================
# Dynamic Position Sizing with Leverage
# ==========================================
def calculate_position_size(
    balance: float,
    entry: float,
    sl_price: float,
    risk_pct: float = RISK_PER_TRADE,
    leverage: int = LEVERAGE
) -> float:
    risk_amount = balance * risk_pct
    risk_per_unit = abs(entry - sl_price)

    if risk_per_unit == 0:
        log("⚠️ SL = Entry — خطأ في الحساب")
        return 0.0

    # With leverage: position size = (risk_amount / risk_per_unit) * leverage
    amount = (risk_amount / risk_per_unit) * leverage
    amount = round(amount, 3)
    amount = max(amount, 0.001)  # Binance minimum

    # Check minimum notional value (~$5 on Binance)
    notional = amount * entry
    if notional < 5:
        amount = 5.0 / entry
        amount = round(amount, 3)
        log(f"📊 Adjusted for min notional: {amount} BTC")

    log(f"📊 Position Size: {amount} BTC | Risk: ${risk_amount:.2f} | Leverage: {leverage}x")
    return amount

# ==========================================
# RR Check with Fees (Corrected)
# ==========================================
def check_rr_with_fees(
    entry: float,
    sl_price: float,
    tp_price: float,
    min_rr: float = MIN_RR_RATIO
) -> tuple[bool, float]:
    risk = abs(sl_price - entry)
    reward = abs(tp_price - entry)

    if risk == 0:
        return False, 0.0

    # Fee as percentage of risk
    fee_cost = entry * FEE_RATE * 2  # Entry + Exit
    fee_pct_of_risk = fee_cost / risk

    real_reward = reward - fee_cost
    real_risk = risk + fee_cost

    if real_risk == 0:
        return False, 0.0

    rr = real_reward / real_risk
    log(f"📐 RR حقيقي: 1:{rr:.2f} | Fee: {fee_pct_of_risk*100:.3f}% of risk")

    if rr < min_rr:
        log(f"❌ RR {rr:.2f} أقل من الحد {min_rr}")
        return False, rr

    return True, rr

# ==========================================
# Liquidation Price Check
# ==========================================
def check_liquidation_price(entry: float, sl: float, leverage: int, signal: str) -> bool:
    """Check if SL is safe from liquidation"""
    if signal == 'BUY':
        liq_price = entry * (1 - 1/leverage + 0.005)  # 0.5% buffer
        if sl <= liq_price:
            log(f"⚠️ SL {sl:.2f} قريب من Liquidation {liq_price:.2f}!")
            return False
    else:  # SELL
        liq_price = entry * (1 + 1/leverage - 0.005)
        if sl >= liq_price:
            log(f"⚠️ SL {sl:.2f} قريب من Liquidation {liq_price:.2f}!")
            return False
    return True

# ==========================================
# Partial TP Levels (Corrected)
# ==========================================
def calculate_tp_levels(
    entry: float,
    tp_final: float,
    sl_price: float,
    signal: str,
    asian_high: float = None,
    asian_low: float = None,
    mo_price: float = None
) -> list[dict]:
    levels = []
    direction = 1 if signal == "BUY" else -1

    # Validate TP direction
    if signal == "BUY" and tp_final <= entry:
        log("⚠️ TP_final أقل من Entry للـ BUY — تعديل")
        tp_final = entry + abs(entry - sl_price) * 2
    if signal == "SELL" and tp_final >= entry:
        log("⚠️ TP_final أعلى من Entry للـ SELL — تعديل")
        tp_final = entry - abs(entry - sl_price) * 2

    # TP1 = 40% of distance (not 50% as comment says)
    tp1 = entry + direction * abs(tp_final - entry) * 0.4

    # TP2 = Asian Range or 70% of distance
    if signal == "BUY" and asian_high and asian_high > entry:
        tp2 = asian_high
    elif signal == "SELL" and asian_low and asian_low < entry:
        tp2 = asian_low
    else:
        tp2 = entry + direction * abs(tp_final - entry) * 0.7

    # Ensure TP2 is on correct side
    if signal == "BUY" and tp2 <= entry:
        tp2 = entry + abs(entry - sl_price) * 1.5
    if signal == "SELL" and tp2 >= entry:
        tp2 = entry - abs(entry - sl_price) * 1.5

    # TP3 = final target
    tp3 = tp_final

    # Break Even after TP1
    be_price = entry + direction * abs(entry - sl_price) * 0.1

    levels = [
        {'level': 'TP1', 'price': round(tp1, 2), 'close_pct': 0.50, 'action': 'partial_close'},
        {'level': 'TP2', 'price': round(tp2, 2), 'close_pct': 0.30, 'action': 'partial_close'},
        {'level': 'TP3', 'price': round(tp3, 2), 'close_pct': 0.20, 'action': 'close_all'},
        {'level': 'BE',  'price': round(be_price, 2), 'close_pct': 0, 'action': 'move_sl_to_be'},
    ]

    for l in levels:
        log(f"🎯 {l['level']}: {l['price']:.2f} ({int(l['close_pct']*100)}%)")

    return levels

# ==========================================
# Volatility-Based Position Sizing
# ==========================================
def calculate_volatility_adjusted_size(
    balance: float,
    entry: float,
    sl_price: float,
    candles: list,
    risk_pct: float = RISK_PER_TRADE
) -> float:
    """Reduce position size in high volatility"""
    if not candles or len(candles) < 10:
        return calculate_position_size(balance, entry, sl_price, risk_pct)

    # Calculate ATR (Average True Range)
    atr_values = []
    for i in range(1, min(15, len(candles))):
        c = candles[i]
        p = candles[i-1]
        tr = max(c[2] - c[3], abs(c[2] - p[4]), abs(c[3] - p[4]))
        atr_values.append(tr)

    atr = sum(atr_values) / len(atr_values) if atr_values else 0
    avg_price = sum(c[4] for c in candles[-10:]) / 10
    volatility_pct = (atr / avg_price) * 100 if avg_price > 0 else 0

    # Adjust risk based on volatility
    adjusted_risk = risk_pct
    if volatility_pct > 2.0:  # High volatility
        adjusted_risk = risk_pct * 0.5
        log(f"📊 High volatility {volatility_pct:.2f}% — Risk reduced to {adjusted_risk*100:.1f}%")
    elif volatility_pct > 1.0:  # Medium volatility
        adjusted_risk = risk_pct * 0.75
        log(f"📊 Medium volatility {volatility_pct:.2f}% — Risk reduced to {adjusted_risk*100:.1f}%")

    return calculate_position_size(balance, entry, sl_price, adjusted_risk)
