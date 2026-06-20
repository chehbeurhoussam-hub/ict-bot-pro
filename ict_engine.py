from datetime import datetime
from config import (
    SYMBOL, TIMEFRAME_EXEC, TIMEFRAME_4H,
    ASIAN_SESSION_CANDLES, LONDON_SESSION_CANDLES,
    FIB_OTE_LOW, FIB_OTE_HIGH, FIB_CE,
    KILL_ZONE_START, KILL_ZONE_END, NY_TZ
)
from state_logger import log

# ==========================================
# FILTER 1 — Kill Zone
# ==========================================
def is_in_kill_zone() -> bool:
    now = datetime.now(NY_TZ)
    ok = KILL_ZONE_START <= now.hour < KILL_ZONE_END
    if not ok:
        log(f"⏳ خارج Kill Zone ({now.strftime('%H:%M')} NY)")
    return ok

# ==========================================
# FILTER 2 — Open Position Check
# ==========================================
def has_open_position(exchange) -> bool:
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            if float(p.get('contracts', 0)) > 0:
                log("📌 صفقة مفتوحة — لا دخول جديد")
                return True
        return False
    except Exception as e:
        log(f"⚠️ خطأ فحص صفقات: {e}")
        return False

# ==========================================
# STEP 1 — Weekly + Daily Timeframe Bias (FIXED EMA)
# ==========================================
def _ema(closes: list, period: int) -> float:
    """Calculate EMA correctly — start from newest data"""
    k = 2 / (period + 1)
    # Start from the most recent candle (end of list)
    ema = closes[-1]
    for price in reversed(closes[:-1]):
        ema = price * k + ema * (1 - k)
    return ema

def get_htf_bias(exchange) -> dict:
    result = {'weekly': 'NEUTRAL', 'daily': 'NEUTRAL', 'confirmed': False}
    try:
        # Weekly EMA
        w_candles = exchange.fetch_ohlcv(SYMBOL, '1w', limit=20)
        w_closes = [c[4] for c in w_candles]
        if len(w_closes) < 10:
            log("⚠️ بيانات Weekly غير كافية")
            return result
        w_ema5 = _ema(w_closes, 5)
        w_ema10 = _ema(w_closes, 10)
        result['weekly'] = 'BULLISH' if w_ema5 > w_ema10 else 'BEARISH'

        # Daily EMA
        d_candles = exchange.fetch_ohlcv(SYMBOL, '1d', limit=50)
        d_closes = [c[4] for c in d_candles]
        if len(d_closes) < 20:
            log("⚠️ بيانات Daily غير كافية")
            return result
        d_ema10 = _ema(d_closes, 10)
        d_ema20 = _ema(d_closes, 20)
        result['daily'] = 'BULLISH' if d_ema10 > d_ema20 else 'BEARISH'

        result['confirmed'] = result['weekly'] == result['daily']

        log(f"🗓️ Weekly: {result['weekly']} | Daily: {result['daily']} | Confirmed: {result['confirmed']}")
        return result

    except Exception as e:
        log(f"⚠️ خطأ HTF: {e}")
        return result

# ==========================================
# STEP 2 — AMD Phase (Power of 3) — FIXED
# ==========================================
def get_amd_bias(exchange) -> dict:
    result = {
        'bias': 'NEUTRAL', 'phase': 'UNKNOWN',
        'asian_high': 0, 'asian_low': 0, 'asian_mid': 0
    }
    try:
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_EXEC, limit=96)
        if len(candles) < ASIAN_SESSION_CANDLES + LONDON_SESSION_CANDLES:
            log("⚠️ بيانات غير كافية لـ AMD")
            return result

        asian = candles[:ASIAN_SESSION_CANDLES]
        london = candles[ASIAN_SESSION_CANDLES:ASIAN_SESSION_CANDLES + LONDON_SESSION_CANDLES]

        asian_high = max(c[2] for c in asian)
        asian_low = min(c[3] for c in asian)
        asian_mid = (asian_high + asian_low) / 2

        result.update({'asian_high': asian_high, 'asian_low': asian_low, 'asian_mid': asian_mid})

        hour = datetime.now(NY_TZ).hour

        # FIXED: Find FIRST break (not any) — determines direction
        broke_high_idx = None
        broke_low_idx = None

        for i, c in enumerate(london):
            if broke_high_idx is None and c[2] > asian_high:
                broke_high_idx = i
            if broke_low_idx is None and c[3] < asian_low:
                broke_low_idx = i

        # Determine bias based on FIRST raid
        if broke_low_idx is not None and (broke_high_idx is None or broke_low_idx < broke_high_idx):
            result['bias'] = 'BULLISH'
        elif broke_high_idx is not None and (broke_low_idx is None or broke_high_idx < broke_low_idx):
            result['bias'] = 'BEARISH'

        if hour < 7:
            result['phase'] = 'ACCUMULATION'
            result['bias'] = 'NEUTRAL'
        elif 7 <= hour < 9:
            result['phase'] = 'MANIPULATION'
        else:
            result['phase'] = 'DISTRIBUTION'

        log(f"⚡ AMD: {result['phase']} | Bias: {result['bias']} | Asian: {asian_low:.0f}–{asian_high:.0f}")
        return result

    except Exception as e:
        log(f"⚠️ خطأ AMD: {e}")
        return result

# ==========================================
# STEP 3 — Midnight Opening (FIXED: uses TIMEFRAME_EXEC)
# ==========================================
def get_midnight_open(exchange) -> float | None:
    try:
        now = datetime.now(NY_TZ)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since_ts = int(midnight.timestamp() * 1000)
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_EXEC, since=since_ts, limit=1)
        if candles:
            mo = candles[0][1]
            log(f"🌙 Midnight Open: {mo:.2f}")
            return mo
        return None
    except Exception as e:
        log(f"⚠️ خطأ MO: {e}")
        return None

# ==========================================
# STEP 4 — 4H Trend (EMA)
# ==========================================
def get_4h_trend(exchange) -> str:
    try:
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_4H, limit=50)
        if len(candles) < 50:
            log("⚠️ بيانات 4H غير كافية")
            return 'NEUTRAL'
        closes = [c[4] for c in candles]
        ema20 = sum(closes[-20:]) / 20
        ema50 = sum(closes) / 50
        trend = 'BULLISH' if ema20 > ema50 else 'BEARISH'
        log(f"📈 4H Trend: {trend} | EMA20={ema20:.0f} EMA50={ema50:.0f}")
        return trend
    except Exception as e:
        log(f"⚠️ خطأ 4H: {e}")
        return 'NEUTRAL'

# ==========================================
# STEP 5 — Fibonacci OTE Zone (FIXED: recent swing only)
# ==========================================
def get_ote_zone(candles: list, direction: str) -> dict:
    # Use recent candles only for relevant swing
    recent_candles = candles[-30:] if len(candles) >= 30 else candles
    highs = [c[2] for c in recent_candles]
    lows = [c[3] for c in recent_candles]
    swing_high = max(highs)
    swing_low = min(lows)
    rng = swing_high - swing_low

    if rng == 0:
        log("⚠️ OTE Range = 0")
        return {'low': 0, 'high': 0, 'sl_ref': 0, 'swing_high': swing_high, 'swing_low': swing_low}

    if direction == 'BULLISH':
        ote_low = swing_high - rng * FIB_OTE_HIGH
        ote_high = swing_high - rng * FIB_OTE_LOW
        sl_ref = swing_high - rng * (FIB_OTE_HIGH + 0.02)
    else:
        ote_low = swing_low + rng * FIB_OTE_LOW
        ote_high = swing_low + rng * FIB_OTE_HIGH
        sl_ref = swing_low + rng * (FIB_OTE_HIGH + 0.02)

    log(f"📐 OTE: {ote_low:.2f}–{ote_high:.2f} | SL Ref: {sl_ref:.2f}")
    return {'low': ote_low, 'high': ote_high, 'sl_ref': sl_ref, 'swing_high': swing_high, 'swing_low': swing_low}

# ==========================================
# STEP 6 — Order Block (FIXED: search from most recent)
# ==========================================
def find_order_block(candles: list, direction: str) -> dict | None:
    # Search from most recent to oldest
    for i in range(len(candles) - 4, max(2, len(candles) - 25), -1):
        c = candles[i]
        next3 = candles[i+1:i+4]

        if direction == 'BULLISH' and c[4] < c[1]:
            if all(nc[4] > c[2] for nc in next3):
                ob = {'high': c[2], 'low': c[3], 'ce': (c[2]+c[3])/2, 'time': c[0], 'index': i}
                log(f"📦 Bullish OB: {ob['low']:.2f}–{ob['high']:.2f}")
                return ob

        if direction == 'BEARISH' and c[4] > c[1]:
            if all(nc[4] < c[3] for nc in next3):
                ob = {'high': c[2], 'low': c[3], 'ce': (c[2]+c[3])/2, 'time': c[0], 'index': i}
                log(f"📦 Bearish OB: {ob['low']:.2f}–{ob['high']:.2f}")
                return ob
    return None

# ==========================================
# STEP 7 — FVG + CE (FIXED: search recent candles)
# ==========================================
def find_fvg(candles: list, direction: str) -> dict | None:
    # Search only recent candles for most relevant FVG
    search_range = min(20, len(candles) - 4)
    for i in range(len(candles) - 3, len(candles) - 3 - search_range, -1):
        if i + 2 >= len(candles):
            continue
        c1, c2, c3 = candles[i], candles[i+1], candles[i+2]

        if direction == 'BULLISH' and c1[2] < c3[3]:
            fvg = {
                'high': c3[3], 'low': c1[2],
                'ce': (c1[2] + c3[3]) / 2,
                'time': c2[0], 'index': i
            }
            log(f"🔲 Bullish FVG: {fvg['low']:.2f}–{fvg['high']:.2f} | CE: {fvg['ce']:.2f}")
            return fvg

        if direction == 'BEARISH' and c1[3] > c3[2]:
            fvg = {
                'high': c1[3], 'low': c3[2],
                'ce': (c1[3] + c3[2]) / 2,
                'time': c2[0], 'index': i
            }
            log(f"🔲 Bearish FVG: {fvg['low']:.2f}–{fvg['high']:.2f} | CE: {fvg['ce']:.2f}")
            return fvg
    return None

# ==========================================
# STEP 8 — Rejection Block (with context check)
# ==========================================
def find_rejection_block(candles: list, direction: str) -> dict | None:
    # Find recent swing points for context
    recent = candles[-20:] if len(candles) >= 20 else candles
    swing_high = max(c[2] for c in recent)
    swing_low = min(c[3] for c in recent)

    for i in range(len(candles) - 2, max(0, len(candles) - 15), -1):
        c = candles[i]
        rng = c[2] - c[3]
        if rng == 0:
            continue
        body = abs(c[4] - c[1])

        if direction == 'BULLISH':
            lower_wick = min(c[1], c[4]) - c[3]
            # Check if near swing low (context)
            near_swing = abs(c[3] - swing_low) / swing_low < 0.01 if swing_low > 0 else False
            if (lower_wick / rng) >= 0.5 and (body / rng) <= 0.3 and near_swing:
                rb = {'high': min(c[1], c[4]), 'low': c[3], 'time': c[0], 'index': i}
                log(f"🚫 Bullish RB عند {rb['low']:.2f}–{rb['high']:.2f}")
                return rb

        if direction == 'BEARISH':
            upper_wick = c[2] - max(c[1], c[4])
            near_swing = abs(c[2] - swing_high) / swing_high < 0.01 if swing_high > 0 else False
            if (upper_wick / rng) >= 0.5 and (body / rng) <= 0.3 and near_swing:
                rb = {'high': c[2], 'low': max(c[1], c[4]), 'time': c[0], 'index': i}
                log(f"🚫 Bearish RB عند {rb['low']:.2f}–{rb['high']:.2f}")
                return rb
    return None

# ==========================================
# STEP 9 — Liquidity Void (FIXED: search recent only)
# ==========================================
def find_liquidity_void(candles: list, direction: str) -> float | None:
    if len(candles) < 15:
        return None
    avg_rng = sum(abs(c[2]-c[3]) for c in candles[-10:]) / 10
    for i in range(len(candles) - 2, max(0, len(candles) - 20), -1):
        c = candles[i]
        rng = c[2] - c[3]
        body = abs(c[4] - c[1])
        if rng >= avg_rng * 3 and rng > 0 and (body / rng) >= 0.8:
            if direction == 'BULLISH' and c[4] > c[1]:
                ce = (c[2] + c[3]) / 2
                log(f"🌊 Bullish LV CE: {ce:.2f}")
                return ce
            if direction == 'BEARISH' and c[4] < c[1]:
                ce = (c[2] + c[3]) / 2
                log(f"🌊 Bearish LV CE: {ce:.2f}")
                return ce
    return None

# ==========================================
# STEP 10 — Confluence Scoring
# ==========================================
def calculate_confluence(ob, fvg, rb, in_ote: bool) -> dict:
    score = 0
    details = []

    if ob:
        score += 1
        details.append('OB ✅')
    else:
        details.append('OB ❌')

    if fvg:
        score += 1
        details.append('FVG ✅')
    else:
        details.append('FVG ❌')

    if rb:
        score += 1
        details.append('RB ✅')
    else:
        details.append('RB ❌')

    if in_ote:
        score += 1
        details.append('OTE ✅')
    else:
        details.append('OTE ❌')

    log(f"⭐ Confluence: {score}/4 | {' | '.join(details)}")
    return {'score': score, 'details': details}

# ==========================================
# MSS — Market Structure Shift (FIXED: 3-candle sequence)
# ==========================================
def check_mss(candles: list, direction: str) -> bool:
    if len(candles) < 3:
        return False

    c1, c2, c3 = candles[-3], candles[-2], candles[-1]

    if direction == 'BULLISH':
        # Break above c1 high, then c3 confirms above c2 high
        if c2[4] > c1[2] and c3[4] > c2[2]:
            log("✅ MSS تأكيد — كسر قمة متتالي")
            return True
    elif direction == 'BEARISH':
        # Break below c1 low, then c3 confirms below c2 low
        if c2[4] < c1[3] and c3[4] < c2[3]:
            log("✅ MSS تأكيد — كسر قاع متتالي")
            return True

    log("⏳ MSS لم يتأكد بعد")
    return False

# ==========================================
# BOS/CHoCH Detection (NEW)
# ==========================================
def detect_bos_choch(candles: list, direction: str) -> dict:
    """Detect Break of Structure (BOS) and Change of Character (CHoCH)"""
    if len(candles) < 10:
        return {'bos': False, 'choch': False}

    recent = candles[-10:]
    highs = [c[2] for c in recent]
    lows = [c[3] for c in recent]

    # Find recent swing points
    swing_high = max(highs[:-3])  # Exclude last 3 candles
    swing_low = min(lows[:-3])

    last3 = candles[-3:]
    last_high = max(c[2] for c in last3)
    last_low = min(c[3] for c in last3)

    result = {'bos': False, 'choch': False}

    if direction == 'BULLISH':
        # BOS: Price breaks above previous swing high
        if last_high > swing_high:
            result['bos'] = True
            log("✅ BOS Bullish — كسر قمة سابقة")
        # CHoCH: Price breaks below previous swing low after uptrend
        if last_low < swing_low:
            result['choch'] = True
            log("⚠️ CHoCH Bearish — تغير اتجاه")
    else:  # BEARISH
        if last_low < swing_low:
            result['bos'] = True
            log("✅ BOS Bearish — كسر قاع سابق")
        if last_high > swing_high:
            result['choch'] = True
            log("⚠️ CHoCH Bullish — تغير اتجاه")

    return result

# ==========================================
# Liquidity Sweep Detection (NEW)
# ==========================================
def detect_liquidity_sweep(candles: list, direction: str) -> bool:
    """Detect if price swept liquidity before returning"""
    if len(candles) < 5:
        return False

    recent = candles[-5:]
    prev = candles[-10:-5] if len(candles) >= 10 else candles[:5]

    prev_high = max(c[2] for c in prev)
    prev_low = min(c[3] for c in prev)

    if direction == 'BULLISH':
        # Sweep below previous low then return above
        swept = any(c[3] < prev_low for c in recent)
        returned = recent[-1][4] > prev_low
        if swept and returned:
            log("✅ Liquidity Sweep Bullish — مسح سيولة ثم ارتداد")
            return True
    else:
        swept = any(c[2] > prev_high for c in recent)
        returned = recent[-1][4] < prev_high
        if swept and returned:
            log("✅ Liquidity Sweep Bearish — مسح سيولة ثم ارتداد")
            return True

    return False

# ==========================================
# Market Regime Detection (NEW)
# ==========================================
def detect_market_regime(candles: list) -> str:
    """Detect if market is trending or ranging"""
    if len(candles) < 20:
        return 'UNKNOWN'

    closes = [c[4] for c in candles[-20:]]
    highs = [c[2] for c in candles[-20:]]
    lows = [c[3] for c in candles[-20:]]

    # ADX-like calculation using simple ranges
    total_range = max(highs) - min(lows)
    avg_candle_range = sum(h - l for h, l in zip(highs, lows)) / len(highs)

    if total_range == 0:
        return 'RANGING'

    # Trend strength ratio
    trend_ratio = total_range / (avg_candle_range * len(highs))

    if trend_ratio > 0.6:
        log(f"📊 Market Regime: TRENDING (ratio: {trend_ratio:.2f})")
        return 'TRENDING'
    else:
        log(f"📊 Market Regime: RANGING (ratio: {trend_ratio:.2f})")
        return 'RANGING'
