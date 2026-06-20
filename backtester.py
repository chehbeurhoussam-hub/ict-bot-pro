from datetime import datetime
from config import SYMBOL, NY_TZ, MIN_RR_RATIO, CONFLUENCE_MIN
from ict_engine import (
    find_order_block, find_fvg, find_rejection_block,
    find_liquidity_void, get_ote_zone, calculate_confluence,
    check_mss, detect_bos_choch, detect_liquidity_sweep, detect_market_regime
)
from risk_manager import check_rr_with_fees, calculate_tp_levels
from state_logger import log

# ==========================================
# Realistic Trade Simulation (FIXED)
# ==========================================
def simulate_outcome(future_candles: list, entry: float,
                     sl: float, tp: float, signal: str) -> str:
    """
    Realistic simulation — checks both high and low in each candle
    If both SL and TP hit in same candle, use the one closer to open
    """
    for c in future_candles:
        o, h, low, close = c[1], c[2], c[3], c[4]

        if signal == 'BUY':
            sl_hit = low <= sl
            tp_hit = h >= tp

            if sl_hit and tp_hit:
                # Both hit — determine which was closer to open
                sl_dist = abs(o - sl)
                tp_dist = abs(o - tp)
                return 'LOSS' if sl_dist < tp_dist else 'WIN'
            elif sl_hit:
                return 'LOSS'
            elif tp_hit:
                return 'WIN'

        else:  # SELL
            sl_hit = h >= sl
            tp_hit = low <= tp

            if sl_hit and tp_hit:
                sl_dist = abs(o - sl)
                tp_dist = abs(o - tp)
                return 'LOSS' if sl_dist < tp_dist else 'WIN'
            elif sl_hit:
                return 'LOSS'
            elif tp_hit:
                return 'WIN'

    return 'OPEN'

# ==========================================
# Main Backtest (FIXED)
# ==========================================
def run_backtest(exchange, lookback_days: int = 30) -> dict:
    log("=" * 40)
    log(f"🧪 بدء Backtest — آخر {lookback_days} يوم")

    try:
        limit = lookback_days * 96  # 96 candles of 15m = 1 day
        candles = exchange.fetch_ohlcv(SYMBOL, '15m', limit=limit)
        log(f"📊 تم جلب {len(candles)} شمعة")
    except Exception as e:
        log(f"❌ خطأ جلب بيانات: {e}")
        return {}

    trades = []
    wins = 0
    losses = 0
    window = 100  # Analysis window

    for i in range(window, len(candles) - 50):
        subset = candles[i - window:i]
        current = candles[i]

        hour = datetime.fromtimestamp(current[0] / 1000, tz=NY_TZ).hour
        if not (7 <= hour < 10):
            continue

        # Get AMD bias for this time (simulated)
        current_price = current[4]

        # Determine direction from recent structure (not both directions)
        recent = subset[-20:]
        highs = [c[2] for c in recent]
        lows = [c[3] for c in recent]

        # Simple bias detection for backtest
        if highs[-1] > max(highs[:-5]) and lows[-1] > min(lows[:-5]):
            direction = 'BULLISH'
        elif lows[-1] < min(lows[:-5]) and highs[-1] < max(highs[:-5]):
            direction = 'BEARISH'
        else:
            continue  # No clear bias

        signal = 'BUY' if direction == 'BULLISH' else 'SELL'

        ob = find_order_block(subset, direction)
        fvg = find_fvg(subset, direction)
        rb = find_rejection_block(subset, direction)
        ote = get_ote_zone(subset, direction)

        in_ote = ote['low'] <= current_price <= ote['high']
        conf = calculate_confluence(ob, fvg, rb, in_ote)

        if conf['score'] < CONFLUENCE_MIN:
            continue
        if not in_ote:
            continue

        # Check MSS
        if not check_mss(subset, direction):
            continue

        # Check BOS/CHoCH
        bos_choch = detect_bos_choch(subset, direction)
        if not bos_choch['bos']:
            continue

        # Check Liquidity Sweep
        sweep = detect_liquidity_sweep(subset, direction)
        if not sweep:
            continue

        entry = fvg['ce'] if fvg else current_price
        sl = ote['sl_ref']
        lv = find_liquidity_void(subset, direction)

        if direction == 'BULLISH':
            tp = lv if lv and lv > entry else entry + abs(entry - sl) * 2
        else:
            tp = lv if lv and lv < entry else entry - abs(entry - sl) * 2

        # Validate TP direction
        if signal == 'BUY' and tp <= entry:
            tp = entry + abs(entry - sl) * 2
        elif signal == 'SELL' and tp >= entry:
            tp = entry - abs(entry - sl) * 2

        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0

        if rr < MIN_RR_RATIO:
            continue

        # Simulate outcome
        future = candles[i:i+50]
        result = simulate_outcome(future, entry, sl, tp, signal)

        if result == 'OPEN':
            continue

        trade = {
            'index': i,
            'signal': signal,
            'entry': round(entry, 2),
            'sl': round(sl, 2),
            'tp': round(tp, 2),
            'rr': round(rr, 2),
            'result': result,
            'confluence': conf['score'],
            'pnl': rr if result == 'WIN' else -1.0
        }
        trades.append(trade)

        if result == 'WIN':
            wins += 1
        else:
            losses += 1

    # Statistics
    total = len(trades)
    win_rate = wins / total * 100 if total > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    avg_rr = sum(t['rr'] for t in trades) / total if total > 0 else 0
    max_dd = _calculate_max_drawdown(trades)

    # Monthly breakdown
    monthly_stats = _calculate_monthly_stats(trades, candles)

    stats = {
        'total_trades': total,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 1),
        'total_pnl_r': round(total_pnl, 2),
        'avg_rr': round(avg_rr, 2),
        'max_drawdown': round(max_dd, 2),
        'expectancy': round(total_pnl / total, 3) if total > 0 else 0,
        'profit_factor': _calculate_profit_factor(trades),
        'monthly_stats': monthly_stats,
        'trades': trades[-20:],  # Last 20 for display
        'all_trades': trades  # All for analysis
    }

    log("=" * 40)
    log(f"📊 نتائج Backtest:")
    log(f"   صفقات: {total} | Win Rate: {win_rate:.1f}%")
    log(f"   PnL: {total_pnl:.2f}R | Max DD: {max_dd:.2f}R")
    log(f"   Avg RR: {avg_rr:.2f} | Expectancy: {stats['expectancy']:.3f}R")
    log(f"   Profit Factor: {stats['profit_factor']:.2f}")
    log("=" * 40)

    return stats

# ==========================================
# Max Drawdown (FIXED: with timestamps)
# ==========================================
def _calculate_max_drawdown(trades: list) -> float:
    if not trades:
        return 0
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd

# ==========================================
# Profit Factor (NEW)
# ==========================================
def _calculate_profit_factor(trades: list) -> float:
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0
    return gross_profit / gross_loss

# ==========================================
# Monthly Stats (NEW)
# ==========================================
def _calculate_monthly_stats(trades: list, candles: list) -> dict:
    if not trades or not candles:
        return {}

    monthly = {}
    for t in trades:
        idx = t['index']
        if idx < len(candles):
            ts = candles[idx][0] / 1000
            dt = datetime.fromtimestamp(ts, tz=NY_TZ)
            month_key = dt.strftime('%Y-%m')

            if month_key not in monthly:
                monthly[month_key] = {'trades': 0, 'wins': 0, 'pnl': 0}

            monthly[month_key]['trades'] += 1
            monthly[month_key]['wins'] += 1 if t['result'] == 'WIN' else 0
            monthly[month_key]['pnl'] += t['pnl']

    # Calculate win rates
    for month in monthly:
        m = monthly[month]
        m['win_rate'] = round(m['wins'] / m['trades'] * 100, 1) if m['trades'] > 0 else 0
        m['pnl'] = round(m['pnl'], 2)

    return monthly
