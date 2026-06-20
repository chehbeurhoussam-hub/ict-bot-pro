import json
import os
import threading
from datetime import datetime
from enum import Enum
from config import NY_TZ, LOG_MAX_LINES, LOG_FILE

# ==========================================
# State Machine
# ==========================================
class BotState(Enum):
    WAITING_KILL_ZONE  = "⏳ خارج Kill Zone"
    SCANNING           = "🔍 يفحص السوق"
    WAITING_OTE        = "📐 ينتظر OTE Zone"
    IN_TRADE           = "📌 في صفقة"
    DAILY_LIMIT_HIT    = "🛑 وصل حد اليوم"
    ERROR              = "❌ خطأ"
    EMERGENCY_STOP     = "🚨 إيقاف طارئ"

class StateManager:
    def __init__(self):
        self.state       = BotState.WAITING_KILL_ZONE
        self.prev_state  = None
        self.state_since = datetime.now(NY_TZ)
        self.trade_data  = {}
        self._lock       = threading.Lock()

    def transition(self, new_state: BotState):
        with self._lock:
            if new_state != self.state:
                self.prev_state  = self.state
                self.state       = new_state
                self.state_since = datetime.now(NY_TZ)
                log(f"🔄 State: {self.prev_state.value} → {self.state.value}")

    def set_trade(self, data: dict):
        with self._lock:
            self.trade_data = data
            self.transition(BotState.IN_TRADE)

    def clear_trade(self):
        with self._lock:
            self.trade_data = {}
            self.transition(BotState.SCANNING)

    def time_in_state(self) -> float:
        with self._lock:
            return (datetime.now(NY_TZ) - self.state_since).total_seconds() / 60

    def emergency_stop(self):
        with self._lock:
            self.transition(BotState.EMERGENCY_STOP)

# ==========================================
# Thread-Safe Logger
# ==========================================
_logs_buffer = []
_log_lock = threading.Lock()

def log(msg: str):
    global _logs_buffer
    ts   = datetime.now(NY_TZ).strftime('%Y-%m-%d %H:%M:%S')
    full = f"[{ts}] {msg}"
    print(full)
    with _log_lock:
        _logs_buffer.append(full)
        if len(_logs_buffer) > LOG_MAX_LINES:
            _logs_buffer.pop(0)

def get_logs(n=30) -> str:
    with _log_lock:
        return "\n".join(reversed(_logs_buffer[-n:]))

def clear_logs():
    global _logs_buffer
    with _log_lock:
        _logs_buffer = []

# ==========================================
# Audit Logger (Security)
# ==========================================
_audit_file = "audit_log.json"
_audit_lock = threading.Lock()

def audit_log(action: str, details: dict = None):
    """سجل أمني لكل عملية حساسة"""
    entry = {
        'timestamp': datetime.now(NY_TZ).isoformat(),
        'action': action,
        'details': details or {}
    }
    with _audit_lock:
        audit = []
        if os.path.exists(_audit_file):
            try:
                with open(_audit_file, 'r') as f:
                    audit = json.load(f)
            except:
                audit = []
        audit.append(entry)
        with open(_audit_file, 'w') as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)

# ==========================================
# Trade Journal (Atomic Write)
# ==========================================
_journal_lock = threading.Lock()

def save_trade(trade: dict):
    with _journal_lock:
        journal = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r') as f:
                    journal = json.load(f)
            except Exception as e:
                log(f"⚠️ خطأ قراءة Journal: {e}")
                journal = []

        trade['saved_at'] = datetime.now(NY_TZ).strftime('%Y-%m-%d %H:%M:%S')
        journal.append(trade)

        # Atomic write: write to temp then rename
        temp_file = LOG_FILE + ".tmp"
        try:
            with open(temp_file, 'w') as f:
                json.dump(journal, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, LOG_FILE)
            log(f"📓 صفقة محفوظة في Journal")
        except Exception as e:
            log(f"❌ خطأ حفظ Journal: {e}")

def load_journal() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        log(f"⚠️ خطأ تحميل Journal: {e}")
        return []

def get_journal_stats() -> dict:
    trades = load_journal()
    if not trades:
        return {}

    closed = [t for t in trades if t.get('result') in ('WIN', 'LOSS', 'BE')]
    wins   = [t for t in closed if t.get('result') == 'WIN']
    losses = [t for t in closed if t.get('result') == 'LOSS']
    total_pnl = sum(t.get('pnl_pct', 0) for t in closed)

    # Calculate max drawdown properly
    equity = 0
    peak = 0
    max_dd = 0
    for t in closed:
        equity += t.get('pnl_pct', 0)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        'total_trades' : len(trades),
        'closed_trades': len(closed),
        'wins'         : len(wins),
        'losses'       : len(losses),
        'win_rate'     : round(len(wins) / len(closed) * 100, 1) if closed else 0,
        'total_pnl_pct': round(total_pnl, 2),
        'avg_rr'       : round(sum(t.get('rr', 0) for t in closed) / len(closed), 2) if closed else 0,
        'max_drawdown' : round(max_dd, 2),
        'consecutive_losses': _count_consecutive_losses(closed),
    }

def _count_consecutive_losses(trades: list) -> int:
    """عدد الخسائر المتتالية الأخيرة"""
    count = 0
    for t in reversed(trades):
        if t.get('result') == 'LOSS':
            count += 1
        else:
            break
    return count
