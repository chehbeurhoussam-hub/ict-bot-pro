import gradio as gr
import plotly.graph_objects as go
from core import core_trading_loop, state_mgr, get_exchange, emergency_stop
from state_logger import get_logs, get_journal_stats, load_journal
from backtester import run_backtest
from news_filter import get_upcoming_news
from telegram_alerts import send_telegram

# ==========================================
# Dashboard Update Functions
# ==========================================
def update_dashboard():
    try:
        return core_trading_loop()
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        send_telegram(f"Dashboard Error: {str(e)}")
        return error_msg

def get_state():
    return f"{state_mgr.state.value} | منذ {state_mgr.time_in_state():.1f} دقيقة"

def get_stats():
    s = get_journal_stats()
    if not s:
        return "لا توجد صفقات مسجلة بعد"
    return (
        f"📊 إجمالي: {s['total_trades']} | مغلقة: {s['closed_trades']}
"
        f"✅ ربح: {s['wins']} | ❌ خسارة: {s['losses']}
"
        f"🎯 Win Rate: {s['win_rate']}%
"
        f"💰 PnL الكلي: {s['total_pnl_pct']}%
"
        f"📐 متوسط RR: {s['avg_rr']}
"
        f"📉 Max Drawdown: {s.get('max_drawdown', 0)}R
"
        f"🔄 خسائر متتالية: {s.get('consecutive_losses', 0)}"
    )

def get_news_display():
    news = get_upcoming_news(hours_ahead=4)
    if not news:
        return "✅ لا أخبار قوية خلال 4 ساعات"
    lines = ["⚠️ أخبار قوية قريبة:
"]
    for n in news:
        lines.append(f"🕐 {n['time']} NY — {n['title']} (خلال {n['diff']})")
    return "
".join(lines)

def get_journal_table():
    trades = load_journal()
    if not trades:
        return []
    rows = []
    for t in reversed(trades[-20:]):
        rows.append([
            t.get('saved_at', '')[:16],
            t.get('signal', ''),
            t.get('entry', ''),
            t.get('sl', ''),
            t.get('tp1', ''),
            f"1:{t.get('rr', 0):.1f}",
            f"{t.get('confluence', 0)}/4",
            t.get('result', 'OPEN'),
            t.get('pnl_pct', 0),
        ])
    return rows

# ==========================================
# Equity Curve Chart (NEW)
# ==========================================
def get_equity_curve():
    trades = load_journal()
    if not trades:
        return go.Figure()

    closed = [t for t in trades if t.get('result') in ('WIN', 'LOSS', 'BE')]
    if not closed:
        return go.Figure()

    equity = [0]
    for t in closed:
        pnl = t.get('pnl_pct', 0)
        if isinstance(pnl, str):
            try:
                pnl = float(pnl)
            except:
                pnl = 0
        equity.append(equity[-1] + pnl)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=equity,
        mode='lines',
        name='Equity Curve',
        line=dict(color='#00ff88', width=2)
    ))
    fig.update_layout(
        title='Equity Curve (R)',
        xaxis_title='Trade #',
        yaxis_title='Cumulative R',
        template='plotly_dark',
        height=400
    )
    return fig

# ==========================================
# Drawdown Chart (NEW)
# ==========================================
def get_drawdown_chart():
    trades = load_journal()
    if not trades:
        return go.Figure()

    closed = [t for t in trades if t.get('result') in ('WIN', 'LOSS', 'BE')]
    if not closed:
        return go.Figure()

    equity = 0
    peak = 0
    drawdowns = [0]
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
        drawdowns.append(dd)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=drawdowns,
        mode='lines',
        name='Drawdown',
        fill='tozeroy',
        line=dict(color='#ff4444', width=2)
    ))
    fig.update_layout(
        title='Drawdown (R)',
        xaxis_title='Trade #',
        yaxis_title='Drawdown',
        template='plotly_dark',
        height=400
    )
    return fig

# ==========================================
# Backtest UI (Enhanced)
# ==========================================
def run_backtest_ui():
    try:
        exchange = get_exchange()
        if not exchange:
            return "❌ فشل الاتصال بـ Binance"

        stats = run_backtest(exchange, lookback_days=30)
        if not stats:
            return "❌ فشل الـ Backtest"

        result = (
            f"🧪 نتائج Backtest (30 يوم):
"
            f"━━━━━━━━━━━━━━━━━━━━━━
"
            f"📊 صفقات: {stats['total_trades']}
"
            f"✅ Win Rate: {stats['win_rate']}%
"
            f"💰 PnL: {stats['total_pnl_r']}R
"
            f"📉 Max Drawdown: {stats['max_drawdown']}R
"
            f"📐 Avg RR: {stats['avg_rr']}
"
            f"🎯 Expectancy: {stats['expectancy']}R/صفقة
"
            f"💎 Profit Factor: {stats.get('profit_factor', 0):.2f}"
        )

        # Monthly breakdown
        if stats.get('monthly_stats'):
            result += "

📅 حسب الشهر:
"
            for month, mstats in stats['monthly_stats'].items():
                result += f"  {month}: {mstats['trades']} صفقات | {mstats['win_rate']}% WR | {mstats['pnl']}R
"

        return result
    except Exception as e:
        return f"❌ خطأ: {str(e)}"

# ==========================================
# Emergency Stop (NEW)
# ==========================================
def trigger_emergency_stop():
    result = emergency_stop()
    return result + "

🚨 EMERGENCY STOP TRIGGERED 🚨"

# ==========================================
# Gradio Interface (Enhanced)
# ==========================================
with gr.Blocks(title="القناص الذكي — ICT Bot Pro", theme=gr.themes.Soft()) as interface:

    gr.Markdown("# 🎯 القناص الذكي — ICT Trading Bot Pro")
    gr.Markdown("استراتيجية ICT كاملة مع إدارة مخاطر متقدمة ومراقبة حية")

    with gr.Tabs():

        # ─── Tab 1: Live Trading ──────────────
        with gr.Tab("📡 Live Trading"):
            with gr.Row():
                with gr.Column(scale=2):
                    log_box = gr.Textbox(
                        label="سجل العمليات المباشر",
                        lines=25,
                        value=get_logs,
                        every=15
                    )
                with gr.Column(scale=1):
                    state_box = gr.Textbox(
                        label="حالة البوت",
                        value=get_state,
                        every=5
                    )
                    stats_box = gr.Textbox(
                        label="إحصائيات الجلسة",
                        value=get_stats,
                        lines=9,
                        every=30
                    )
                    news_box = gr.Textbox(
                        label="📰 أخبار قريبة",
                        value=get_news_display,
                        lines=5,
                        every=300
                    )

                    # Emergency Stop Button (NEW)
                    gr.Markdown("---")
                    gr.Markdown("### 🚨 Emergency Controls")
                    emergency_btn = gr.Button("🛑 EMERGENCY STOP", variant="stop", size="lg")
                    emergency_output = gr.Textbox(label="نتيجة", lines=3)
                    emergency_btn.click(fn=trigger_emergency_stop, outputs=emergency_output)

                    gr.Markdown("### ⚙️ الإعدادات النشطة")
                    gr.Markdown("""
                    - 🕐 Kill Zone: 7–10 AM NY
                    - 📉 Max Loss: -2% يومياً
                    - 📈 Max Profit: +4% يومياً
                    - ⭐ Confluence: 2/4 على الأقل
                    - 📐 Min RR: 1:1.5
                    - 💰 Risk/Trade: 1%
                    - ⚡ Leverage: 5x
                    - 🔒 Margin: ISOLATED
                    """)

        # ─── Tab 2: Charts (NEW) ─────────────
        with gr.Tab("📊 Analytics"):
            with gr.Row():
                equity_chart = gr.Plot(label="Equity Curve", value=get_equity_curve, every=60)
                dd_chart = gr.Plot(label="Drawdown", value=get_drawdown_chart, every=60)

        # ─── Tab 3: Journal ──────────────────
        with gr.Tab("📓 Trade Journal"):
            journal_table = gr.Dataframe(
                headers=["الوقت", "إشارة", "دخول", "SL", "TP1", "RR", "Confluence", "النتيجة", "PnL"],
                value=get_journal_table,
                every=60,
                label="آخر 20 صفقة"
            )
            stats_full = gr.Textbox(
                label="إحصائيات كاملة",
                value=get_stats,
                every=60
            )

        # ─── Tab 4: Backtest ─────────────────
        with gr.Tab("🧪 Backtest"):
            gr.Markdown("### اختبر الاستراتيجية على بيانات تاريخية (30 يوم)")
            bt_btn = gr.Button("▶️ تشغيل Backtest", variant="primary")
            bt_result = gr.Textbox(label="النتائج", lines=15)
            bt_btn.click(fn=run_backtest_ui, outputs=bt_result)

        # ─── Tab 5: About ────────────────────
        with gr.Tab("📚 المفاهيم"):
            gr.Markdown("""
            ## مفاهيم ICT المستخدمة

            | المفهوم | الدور | الحالة |
            |---|---|---|
            | **الدورة السعرية** | إطار عام للسوق | ✅ |
            | **Power of 3 (AMD)** | Accumulate · Manipulate · Distribute | ✅ |
            | **Daily Profile** | Asian · London · NY Sessions | ✅ |
            | **Midnight Opening** | مرجع اليوم + تأكيد الاتجاه | ✅ |
            | **HTF Confluence** | Weekly + Daily + 4H | ✅ |
            | **OTE (Fibonacci)** | منطقة الدخول المثالية 61.8–79% | ✅ |
            | **Order Block** | أوامر مؤسسية | ✅ |
            | **FVG + CE** | فجوة سعرية + منتصفها | ✅ |
            | **Rejection Block** | رفض سعري قوي | ✅ |
            | **MSS** | تأكيد كسر البنية | ✅ |
            | **BOS/CHoCH** | كسر/تغير البنية | ✅ جديد |
            | **Liquidity Sweep** | مسح السيولة | ✅ جديد |
            | **Liquidity Void** | هدف الصفقة | ✅ |
            | **Partial TP** | TP1 50% · TP2 30% · TP3 20% | ✅ |
            | **Break Even** | تحريك SL بعد TP1 | ✅ |
            | **Position Sizing** | 1% risk ديناميكي | ✅ |
            | **Leverage** | إدارة الرافعة | ✅ جديد |
            | **Liquidation Guard** | حماية من التصفية | ✅ جديد |
            | **Market Regime** | Trending vs Ranging | ✅ جديد |
            | **Consecutive Loss Stop** | توقف بعد 3 خسائر | ✅ جديد |
            | **Max Drawdown Stop** | توقف عند 10% drawdown | ✅ جديد |
            | **Telegram Alerts** | تنبيهات فورية | ✅ جديد |
            | **Emergency Stop** | إيقاف طارئ | ✅ جديد |
            | **Audit Logging** | سجل أمني | ✅ جديد |
            """)

interface.launch()
