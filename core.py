import ccxt
from config import (
    API_KEY, SECRET_KEY, SYMBOL, TIMEFRAME_EXEC,
    CONFLUENCE_MIN, MIN_RR_RATIO, USE_SANDBOX
)
from state_logger import log, get_logs, BotState, StateManager, audit_log
from risk_manager import (
    check_daily_pnl, check_rr_with_fees, calculate_tp_levels,
    check_liquidation_price, calculate_volatility_adjusted_size
)
from ict_engine import (
    is_in_kill_zone, has_open_position,
    get_htf_bias, get_amd_bias, get_midnight_open,
    get_4h_trend, get_ote_zone,
    find_order_block, find_fvg, find_rejection_block,
    find_liquidity_void, calculate_confluence, check_mss,
    detect_bos_choch, detect_liquidity_sweep, detect_market_regime
)
from executor import (
    execute_trade, move_sl_to_breakeven, emergency_close,
    check_position_status, get_active_orders
)
from news_filter import is_safe_to_trade, get_upcoming_news

# ==========================================
# Exchange Setup with Error Handling
# ==========================================
_exchange = None

def get_exchange():
    global _exchange
    if _exchange is not None:
        return _exchange

    try:
        if not API_KEY or not SECRET_KEY:
            log("❌ API Keys مفقودة! يرجى تعيين BINANCE_API_KEY و BINANCE_SECRET")
            return None

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': SECRET_KEY,
            'options': {'defaultType': 'future'},
            'enableRateLimit': True,
            'timeout': 30000,
        })

        if USE_SANDBOX:
            exchange.set_sandbox_mode(True)
            log("🧪 Sandbox mode مفعّل")
        else:
            log("⚠️⚠️⚠️ PRODUCTION MODE — تداول حقيقي!")
            audit_log('PRODUCTION_MODE_ACTIVATED', {})

        # Test connection
        exchange.load_markets()
        log("✅ اتصال بـ Binance Futures ناجح")
        _exchange = exchange
        return exchange

    except Exception as e:
        log(f"❌ فشل الاتصال بـ Binance: {e}")
        return None

# State Manager
state_mgr = StateManager()

# ==========================================
# Connection Retry Decorator
# ==========================================
def with_retry(max_retries=3, delay=2):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    log(f"⚠️ محاولة {attempt + 1}/{max_retries} فشلت: {e}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(delay)
                    else:
                        raise
            return None
        return wrapper
    return decorator

# ==========================================
# Main Trading Loop (FIXED)
# ==========================================
@with_retry(max_retries=3)
def core_trading_loop() -> str:
    log("─" * 35)

    # ─── 0. Exchange Connection ─────────────
    exchange = get_exchange()
    if not exchange:
        state_mgr.transition(BotState.ERROR)
        return get_logs()

    # ─── 1. Kill Zone ───────────────────────
    if not is_in_kill_zone():
        state_mgr.transition(BotState.WAITING_KILL_ZONE)
        return get_logs()

    state_mgr.transition(BotState.SCANNING)

    # ─── 2. News Filter ─────────────────────
    safe, news_msg = is_safe_to_trade()
    if not safe:
        log(news_msg)
        return get_logs()

    # ─── 3. Daily PnL Guard ─────────────────
    ok, pnl_msg = check_daily_pnl(exchange)
    if not ok:
        state_mgr.transition(BotState.DAILY_LIMIT_HIT)
        return get_logs()

    # ─── 4. Open Position Check ───────────────
    if has_open_position(exchange):
        # Check if we need to move SL to BE
        pos = check_position_status(exchange)
        if pos.get('has_position'):
            _check_and_move_be(exchange, pos)
        state_mgr.transition(BotState.IN_TRADE)
        return get_logs()

    # ─── 5. Market Regime Detection (NEW) ─────
    try:
        candles_regime = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_EXEC, limit=30)
        regime = detect_market_regime(candles_regime)
        if regime == 'RANGING':
            log("📊 السوق في نطاق — تقليل الفرص")
            # Continue but be more strict
    except Exception as e:
        log(f"⚠️ خطأ regime detection: {e}")

    # ─── 6. HTF Bias (Weekly + Daily) ────────
    htf = get_htf_bias(exchange)
    if not htf['confirmed']:
        log(f"⚠️ Weekly ({htf['weekly']}) ≠ Daily ({htf['daily']}) — لا دخول")
        return get_logs()

    htf_direction = htf['daily']

    # ─── 7. AMD Phase ────────────────────────
    amd = get_amd_bias(exchange)
    if amd['bias'] == 'NEUTRAL':
        log("↔️ AMD غير واضح — انتظار")
        return get_logs()

    # AMD must align with HTF
    if amd['bias'] != htf_direction:
        log(f"⚠️ AMD ({amd['bias']}) ≠ HTF ({htf_direction}) — لا دخول")
        return get_logs()

    # ─── 8. Midnight Open Filter ────────────
    mo = get_midnight_open(exchange)
    try:
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_EXEC, limit=50)
        current_price = candles[-1][4]
    except Exception as e:
        log(f"⚠️ خطأ جلب بيانات: {e}")
        return get_logs()

    if mo:
        if amd['bias'] == 'BULLISH' and current_price < mo:
            log(f"⚠️ السعر ({current_price:.0f}) تحت MO ({mo:.0f}) — لا BUY")
            return get_logs()
        if amd['bias'] == 'BEARISH' and current_price > mo:
            log(f"⚠️ السعر ({current_price:.0f}) فوق MO ({mo:.0f}) — لا SELL")
            return get_logs()

    # ─── 9. 4H Trend ────────────────────────
    trend_4h = get_4h_trend(exchange)
    if trend_4h != amd['bias']:
        log(f"⚠️ 4H ({trend_4h}) ≠ AMD ({amd['bias']}) — لا دخول")
        return get_logs()

    # ─── 10. OTE Zone ───────────────────────
    ote = get_ote_zone(candles, amd['bias'])
    in_ote = ote['low'] <= current_price <= ote['high']
    if not in_ote:
        log(f"📐 السعر خارج OTE ({ote['low']:.0f}–{ote['high']:.0f}) — انتظار")
        state_mgr.transition(BotState.WAITING_OTE)
        return get_logs()

    # ─── 11. BOS/CHoCH Detection (NEW) ───────
    bos_choch = detect_bos_choch(candles, amd['bias'])
    if not bos_choch['bos'] and not bos_choch['choch']:
        log("⏳ لا يوجد BOS/CHoCH — انتظار تأكيد")
        return get_logs()

    # ─── 12. Liquidity Sweep (NEW) ──────────
    sweep = detect_liquidity_sweep(candles, amd['bias'])
    if not sweep:
        log("⏳ لا يوجد Liquidity Sweep — انتظار")
        return get_logs()

    # ─── 13. Confluence (OB + FVG + RB) ──────
    ob = find_order_block(candles, amd['bias'])
    fvg = find_fvg(candles, amd['bias'])
    rb = find_rejection_block(candles, amd['bias'])
    conf = calculate_confluence(ob, fvg, rb, in_ote)

    if conf['score'] < CONFLUENCE_MIN:
        log(f"❌ Confluence {conf['score']}/4 — يحتاج {CONFLUENCE_MIN} على الأقل")
        return get_logs()

    # ─── 14. MSS Confirmation ────────────────
    if not check_mss(candles, amd['bias']):
        log("⏳ ننتظر تأكيد MSS")
        return get_logs()

    # ─── 15. Entry Point ────────────────────
    entry = fvg['ce'] if fvg else (ob['ce'] if ob else current_price)
    sl = ote['sl_ref']

    # FIXED: Validate entry is realistic
    if abs(entry - current_price) / current_price > 0.01:
        log(f"⚠️ Entry {entry:.2f} بعيد عن السعر الحالي {current_price:.2f}")
        entry = current_price  # Use current price instead

    # ─── 16. TP Levels ───────────────────────
    lv_ce = find_liquidity_void(candles, amd['bias'])

    if lv_ce:
        tp_final = lv_ce
    elif amd['bias'] == 'BULLISH':
        tp_final = amd['asian_high']
    else:
        tp_final = amd['asian_low']

    # FIXED: Validate TP direction
    signal = 'BUY' if amd['bias'] == 'BULLISH' else 'SELL'
    if signal == 'BUY' and tp_final <= entry:
        tp_final = entry + abs(entry - sl) * 2
        log(f"📐 TP adjusted to {tp_final:.2f}")
    elif signal == 'SELL' and tp_final >= entry:
        tp_final = entry - abs(entry - sl) * 2
        log(f"📐 TP adjusted to {tp_final:.2f}")

    tp_levels = calculate_tp_levels(
        entry, tp_final, sl, signal,
        amd['asian_high'], amd['asian_low'], mo
    )

    # ─── 17. Weighted RR Check (FIXED: or instead of and) ──
    tp1_price = tp_levels[0]['price']
    tp2_price = tp_levels[1]['price']
    tp3_price = tp_levels[2]['price']

    weighted_tp = (
        abs(tp1_price - entry) * 0.50 +
        abs(tp2_price - entry) * 0.30 +
        abs(tp3_price - entry) * 0.20
    )
    sl_dist = abs(entry - sl)
    rr_weighted = weighted_tp / sl_dist if sl_dist > 0 else 0
    log(f"📐 RR مرجح: 1:{rr_weighted:.2f} (TP1×50% + TP2×30% + TP3×20%)")

    # FIXED: Check RR with fees on TP1
    rr_ok, rr = check_rr_with_fees(entry, sl, tp1_price)
    if not rr_ok or rr_weighted < MIN_RR_RATIO:
        log(f"❌ RR مرجح {rr_weighted:.2f} أو RR حقيقي {rr:.2f} أقل من الحد {MIN_RR_RATIO}")
        return get_logs()

    # ─── 18. Liquidation Check (NEW) ────────
    from config import LEVERAGE
    if not check_liquidation_price(entry, sl, LEVERAGE, signal):
        log("❌ SL قريب جداً من سعر التصفية!")
        return get_logs()

    # ─── 19. Get Balance ────────────────────
    try:
        balance_data = exchange.fetch_balance()
        balance = float(balance_data['free']['USDT']) + float(balance_data['used']['USDT'])
    except Exception as e:
        log(f"⚠️ خطأ جلب الرصيد: {e}")
        return get_logs()

    if balance < 10:
        log("❌ رصيد غير كافي (< 10 USDT)")
        return get_logs()

    # ─── 20. Execute Trade ──────────────────
    log("=" * 35)
    log(f"💎 إشارة مثالية!")
    log(f"   {signal} | Entry: {entry:.2f}")
    log(f"   SL: {sl:.2f} | RR: 1:{rr:.2f}")
    log(f"   Confluence: {conf['score']}/4")
    log(f"   AMD: {amd['phase']} | HTF: {htf_direction}")
    log(f"   Regime: {regime} | BOS: {bos_choch['bos']}")
    log("=" * 35)

    meta = {
        'rr': rr_weighted,
        'confluence': conf['score'],
        'amd_bias': amd['bias'],
        'phase': amd['phase'],
        'regime': regime,
        'bos': bos_choch['bos'],
    }

    trade = execute_trade(exchange, signal, entry, sl, tp_levels, balance, meta)

    if trade:
        state_mgr.set_trade(trade)
        audit_log('TRADE_EXECUTED', {
            'signal': signal, 'entry': entry, 'sl': sl,
            'rr': rr_weighted, 'confluence': conf['score']
        })

    return get_logs()

# ==========================================
# Check and Move SL to Break Even (NEW)
# ==========================================
def _check_and_move_be(exchange, pos: dict):
    """Check if position is in profit and move SL to BE"""
    try:
        unrealized = pos.get('unrealized_pnl', 0)
        entry = pos.get('entry_price', 0)
        side = pos.get('side', '')

        if unrealized <= 0:
            return

        # Check if we have enough profit to move to BE (e.g., 0.5%)
        profit_pct = abs(unrealized) / (entry * pos['contracts']) if entry > 0 else 0
        if profit_pct < 0.005:  # 0.5%
            return

        # Get active orders to find current SL
        active = get_active_orders()
        if not active.get('sl'):
            return

        # Move SL to BE
        signal = 'BUY' if side == 'long' else 'SELL'
        move_sl_to_breakeven(exchange, signal, pos['contracts'], entry)

    except Exception as e:
        log(f"⚠️ خطأ فحص BE: {e}")

# ==========================================
# Emergency Stop (NEW)
# ==========================================
def emergency_stop():
    """Emergency stop — close all positions and cancel orders"""
    log("🚨🚨🚨 EMERGENCY STOP 🚨🚨🚨")
    state_mgr.emergency_stop()
    audit_log('EMERGENCY_STOP', {})

    exchange = get_exchange()
    if exchange:
        emergency_close(exchange)
    return get_logs()
