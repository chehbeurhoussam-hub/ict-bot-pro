import ccxt
from config import SYMBOL, FEE_RATE, LEVERAGE, MARGIN_TYPE
from state_logger import log, save_trade, audit_log
from risk_manager import calculate_position_size

# ==========================================
# Order Tracking (NEW)
# ==========================================
_active_orders = {}  # {symbol: {order_type: order_id}}

def get_active_orders():
    return _active_orders.get(SYMBOL, {})

def set_active_order(order_type: str, order_id: str):
    if SYMBOL not in _active_orders:
        _active_orders[SYMBOL] = {}
    _active_orders[SYMBOL][order_type] = order_id

def clear_active_orders():
    if SYMBOL in _active_orders:
        _active_orders[SYMBOL] = {}

# ==========================================
# Cancel Orders (FIXED: only our orders)
# ==========================================
def cancel_existing_orders(exchange):
    try:
        open_orders = exchange.fetch_open_orders(SYMBOL)
        cancelled = 0
        for o in open_orders:
            # Only cancel stop/take_profit orders (not manual limit orders)
            if o.get('type') in ('stop_market', 'take_profit_market', 'stop', 'take_profit'):
                try:
                    exchange.cancel_order(o['id'], SYMBOL)
                    cancelled += 1
                    log(f"🗑️ تم إلغاء أمر قديم: {o['id']} ({o.get('type')})")
                except Exception as e:
                    log(f"⚠️ تعذر إلغاء {o['id']}: {e}")
        if cancelled == 0:
            log("✅ لا أوامر معلقة قديمة")
        audit_log('CANCEL_ORDERS', {'cancelled': cancelled})
    except Exception as e:
        log(f"⚠️ خطأ إلغاء أوامر: {e}")

# ==========================================
# Validate Order Before Sending (NEW)
# ==========================================
def validate_order(exchange, signal: str, entry: float, sl: float, tp: float, amount: float) -> tuple[bool, str]:
    """Validate order parameters before sending"""
    try:
        # Get symbol info
        markets = exchange.load_markets()
        market = markets.get(SYMBOL)
        if not market:
            return False, "Symbol not found"

        # Check minimum amount
        min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.001)
        if amount < min_amount:
            return False, f"Amount {amount} < min {min_amount}"

        # Check minimum notional
        min_notional = market.get('limits', {}).get('cost', {}).get('min', 5)
        if entry * amount < min_notional:
            return False, f"Notional {entry*amount:.2f} < min {min_notional}"

        # Check price precision
        price_precision = market.get('precision', {}).get('price', 2)
        tick_size = 10 ** (-price_precision)

        # Validate SL and TP are on correct side
        if signal == 'BUY':
            if sl >= entry:
                return False, f"SL {sl} >= Entry {entry} for BUY"
            if tp <= entry:
                return False, f"TP {tp} <= Entry {entry} for BUY"
        else:  # SELL
            if sl <= entry:
                return False, f"SL {sl} <= Entry {entry} for SELL"
            if tp >= entry:
                return False, f"TP {tp} >= Entry {entry} for SELL"

        # Check leverage and margin type
        try:
            exchange.set_leverage(LEVERAGE, SYMBOL)
            if MARGIN_TYPE == 'ISOLATED':
                exchange.set_margin_mode('ISOLATED', SYMBOL)
        except Exception as e:
            log(f"⚠️ Leverage/Margin setting: {e}")

        return True, "Valid"

    except Exception as e:
        return False, f"Validation error: {e}"

# ==========================================
# Execute Trade (FIXED: bracket order, validation, error handling)
# ==========================================
def execute_trade(exchange, signal: str, entry: float, sl_price: float,
                  tp_levels: list, balance: float, meta: dict) -> dict | None:
    try:
        # Calculate position size with leverage
        amount = calculate_position_size(balance, entry, sl_price)
        sl_side = 'sell' if signal == 'BUY' else 'buy'

        if amount <= 0:
            log("❌ حجم الصفقة = 0 — لا تنفيذ")
            return None

        # Validate order
        tp_final = tp_levels[2]['price'] if len(tp_levels) > 2 else entry
        valid, msg = validate_order(exchange, signal, entry, sl_price, tp_final, amount)
        if not valid:
            log(f"❌ Order validation failed: {msg}")
            audit_log('ORDER_REJECTED', {'reason': msg})
            return None

        log(f"🚀 تنفيذ {signal} | Amount: {amount} | Entry: {entry:.2f}")

        # Cancel old orders first
        cancel_existing_orders(exchange)

        # Open position (market order for now — can be changed to limit)
        order = exchange.create_order(
            SYMBOL, 'market', signal.lower(), amount
        )
        log(f"✅ صفقة مفتوحة! ID: {order['id']}")
        audit_log('TRADE_OPENED', {
            'signal': signal, 'entry': entry, 'amount': amount, 'order_id': order['id']
        })

        # Track the main order
        set_active_order('entry', order['id'])

        # Set Stop Loss
        try:
            sl_order = exchange.create_order(SYMBOL, 'stop_market', sl_side, amount, params={
                'stopPrice': round(sl_price, 2),
                'reduceOnly': True
            })
            set_active_order('sl', sl_order['id'])
            log(f"🛑 SL: {sl_price:.2f} | Order: {sl_order['id']}")
        except Exception as e:
            log(f"❌ فشل SL: {e} — إغلاق الصفقة!")
            audit_log('SL_FAILED', {'error': str(e)})
            emergency_close(exchange)
            return None

        # Take Profit 1
        tp1 = next((t for t in tp_levels if t['level'] == 'TP1'), None)
        if tp1:
            try:
                tp1_amount = round(amount * tp1['close_pct'], 3)
                tp1_order = exchange.create_order(SYMBOL, 'take_profit_market', sl_side, tp1_amount, params={
                    'stopPrice': tp1['price'],
                    'reduceOnly': True
                })
                set_active_order('tp1', tp1_order['id'])
                log(f"🎯 TP1: {tp1['price']:.2f} ({tp1_amount} BTC) | Order: {tp1_order['id']}")
            except Exception as e:
                log(f"⚠️ فشل TP1: {e}")

        # Take Profit 2
        tp2 = next((t for t in tp_levels if t['level'] == 'TP2'), None)
        if tp2:
            try:
                tp2_amount = round(amount * tp2['close_pct'], 3)
                tp2_order = exchange.create_order(SYMBOL, 'take_profit_market', sl_side, tp2_amount, params={
                    'stopPrice': tp2['price'],
                    'reduceOnly': True
                })
                set_active_order('tp2', tp2_order['id'])
                log(f"🎯 TP2: {tp2['price']:.2f} ({tp2_amount} BTC) | Order: {tp2_order['id']}")
            except Exception as e:
                log(f"⚠️ فشل TP2: {e}")

        # Take Profit 3 (remaining)
        tp3 = next((t for t in tp_levels if t['level'] == 'TP3'), None)
        if tp3:
            try:
                # Calculate remaining amount to avoid rounding issues
                tp1_amt = tp1['close_pct'] * amount if tp1 else 0
                tp2_amt = tp2['close_pct'] * amount if tp2 else 0
                tp3_amount = round(amount - tp1_amt - tp2_amt, 3)
                tp3_amount = max(tp3_amount, 0.001)

                tp3_order = exchange.create_order(SYMBOL, 'take_profit_market', sl_side, tp3_amount, params={
                    'stopPrice': tp3['price'],
                    'reduceOnly': True
                })
                set_active_order('tp3', tp3_order['id'])
                log(f"🎯 TP3: {tp3['price']:.2f} ({tp3_amount} BTC) | Order: {tp3_order['id']}")
            except Exception as e:
                log(f"⚠️ فشل TP3: {e}")

        # Save to journal
        trade_record = {
            'signal': signal,
            'entry': entry,
            'sl': sl_price,
            'tp1': tp1['price'] if tp1 else None,
            'tp2': tp2['price'] if tp2 else None,
            'tp3': tp3['price'] if tp3 else None,
            'amount': amount,
            'order_id': order['id'],
            'active_orders': get_active_orders(),
            'result': 'OPEN',
            'pnl_pct': 0,
            'rr': meta.get('rr', 0),
            'confluence': meta.get('confluence', 0),
            'amd_bias': meta.get('amd_bias', ''),
            'phase': meta.get('phase', ''),
        }
        save_trade(trade_record)
        return trade_record

    except Exception as e:
        log(f"❌ فشل التنفيذ: {e}")
        audit_log('EXECUTION_FAILED', {'error': str(e)})
        return None

# ==========================================
# Move SL to Break Even (FIXED: cancel old first)
# ==========================================
def move_sl_to_breakeven(exchange, signal: str, amount: float, entry: float):
    try:
        # Cancel old SL first
        active = get_active_orders()
        old_sl_id = active.get('sl')
        if old_sl_id:
            try:
                exchange.cancel_order(old_sl_id, SYMBOL)
                log(f"🗑️ SL قديم أُلغي: {old_sl_id}")
            except Exception as e:
                log(f"⚠️ تعذر إلغاء SL قديم: {e}")

        sl_side = 'sell' if signal == 'BUY' else 'buy'
        be_price = round(entry * (1 + FEE_RATE * 2), 2) if signal == 'BUY'                    else round(entry * (1 - FEE_RATE * 2), 2)

        new_sl = exchange.create_order(SYMBOL, 'stop_market', sl_side, amount, params={
            'stopPrice': be_price,
            'reduceOnly': True
        })
        set_active_order('sl', new_sl['id'])
        log(f"🔒 SL حُرِّك إلى Break Even: {be_price:.2f} | Order: {new_sl['id']}")
        audit_log('SL_MOVED_BE', {'price': be_price, 'order_id': new_sl['id']})

    except Exception as e:
        log(f"⚠️ خطأ Break Even: {e}")

# ==========================================
# Emergency Close (FIXED: retry logic)
# ==========================================
def emergency_close(exchange):
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            contracts = float(p.get('contracts', 0))
            if contracts > 0:
                side = 'sell' if p['side'] == 'long' else 'buy'
                # Retry up to 3 times
                for attempt in range(3):
                    try:
                        order = exchange.create_order(
                            SYMBOL, 'market', side, contracts,
                            params={'reduceOnly': True}
                        )
                        log(f"🚨 إغلاق طارئ! {contracts} {SYMBOL} | Order: {order['id']}")
                        audit_log('EMERGENCY_CLOSE', {
                            'contracts': contracts, 'side': side, 'order_id': order['id']
                        })
                        clear_active_orders()
                        break
                    except Exception as e:
                        log(f"⚠️ محاولة إغلاق {attempt+1}/3 فشلت: {e}")
                        if attempt == 2:
                            log("❌ فشل الإغلاق الطارئ بعد 3 محاولات!")
    except Exception as e:
        log(f"❌ خطأ إغلاق طارئ: {e}")
        audit_log('EMERGENCY_CLOSE_FAILED', {'error': str(e)})

# ==========================================
# Check Position Status (NEW)
# ==========================================
def check_position_status(exchange) -> dict:
    """Check current position and PnL"""
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            contracts = float(p.get('contracts', 0))
            if contracts > 0:
                return {
                    'has_position': True,
                    'side': p['side'],
                    'contracts': contracts,
                    'entry_price': float(p.get('entryPrice', 0)),
                    'unrealized_pnl': float(p.get('unrealizedPnl', 0)),
                    'liquidation_price': float(p.get('liquidationPrice', 0)),
                    'leverage': float(p.get('leverage', 1)),
                }
        return {'has_position': False}
    except Exception as e:
        log(f"⚠️ خطأ فحص المركز: {e}")
        return {'has_position': False, 'error': str(e)}
