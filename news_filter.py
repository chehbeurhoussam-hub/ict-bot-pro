import urllib.request
import json
from datetime import datetime, timedelta
from config import NY_TZ
from state_logger import log

# ==========================================
# High Impact News to Avoid
# ==========================================
HIGH_IMPACT_KEYWORDS = [
    'CPI', 'Core CPI', 'Inflation',
    'NFP', 'Non-Farm', 'Unemployment',
    'FOMC', 'Fed', 'Interest Rate', 'Rate Decision',
    'GDP', 'Retail Sales',
    'PPI', 'PCE',
    'Powell', 'Yellen',
    'ISM', 'PMI'
]

# Buffer minutes before and after news
NEWS_BUFFER_BEFORE = 30
NEWS_BUFFER_AFTER = 30

# Cache to avoid repeated requests
_news_cache = {
    'data': [],
    'fetched_at': None
}

# ==========================================
# Fetch Economic Calendar (FIXED timezone)
# ==========================================
def fetch_economic_calendar() -> list:
    global _news_cache

    now = datetime.now(NY_TZ)

    # Use cache if less than 1 hour old
    if _news_cache['fetched_at']:
        age = (now - _news_cache['fetched_at']).total_seconds() / 60
        if age < 60:
            return _news_cache['data']

    try:
        req = urllib.request.Request(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        _news_cache['data'] = data if isinstance(data, list) else []
        _news_cache['fetched_at'] = now
        log(f"📰 تم جلب {len(_news_cache['data'])} خبر من التقويم")
        return _news_cache['data']

    except Exception as e:
        log(f"⚠️ تعذر جلب التقويم: {e} — نستخدم Fallback")
        return _fetch_fallback_calendar()

# ==========================================
# Fallback — Fixed News Times (FIXED: check weekday)
# ==========================================
def _fetch_fallback_calendar() -> list:
    now = datetime.now(NY_TZ)
    today = now.strftime('%Y-%m-%d')
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    # Only add events on relevant days
    fixed_times = []

    # NFP: First Friday of every month
    if weekday == 4 and 1 <= now.day <= 7:  # Friday, first week
        fixed_times.append({'time': f'{today} 08:30', 'title': 'NFP Non-Farm Payrolls', 'impact': 'High'})

    # CPI: Second week of every month (approximate)
    if 8 <= now.day <= 14:
        fixed_times.append({'time': f'{today} 08:30', 'title': 'CPI Inflation Report', 'impact': 'High'})

    # FOMC: 8 times per year (approximate Wednesdays)
    if weekday == 2 and now.day in [17, 18, 19]:  # Approximate FOMC dates
        fixed_times.append({'time': f'{today} 14:00', 'title': 'FOMC Rate Decision', 'impact': 'High'})
        fixed_times.append({'time': f'{today} 14:30', 'title': 'Powell Press Conference', 'impact': 'High'})

    # Weekly claims: Every Thursday
    if weekday == 3:
        fixed_times.append({'time': f'{today} 08:30', 'title': 'Initial Jobless Claims', 'impact': 'Medium'})

    return fixed_times

# ==========================================
# Main Filter
# ==========================================
def is_safe_to_trade() -> tuple[bool, str]:
    now = datetime.now(NY_TZ)
    calendar = fetch_economic_calendar()

    for event in calendar:
        event_time = _parse_event_time(event)
        if not event_time:
            continue

        if not _is_high_impact(event):
            continue

        diff_minutes = (event_time - now).total_seconds() / 60

        # Before news
        if 0 < diff_minutes <= NEWS_BUFFER_BEFORE:
            msg = f"⛔ خبر قوي خلال {int(diff_minutes)} دقيقة: {_get_title(event)}"
            log(msg)
            return False, msg

        # After news
        if -NEWS_BUFFER_AFTER <= diff_minutes <= 0:
            msg = f"⛔ مرّ خبر قوي منذ {int(abs(diff_minutes))} دقيقة: {_get_title(event)}"
            log(msg)
            return False, msg

    log("✅ لا أخبار قوية قريبة — آمن للتداول")
    return True, ""

# ==========================================
# Helper Functions (FIXED: timezone)
# ==========================================
def _parse_event_time(event: dict) -> datetime | None:
    try:
        for key in ('date', 'time', 'datetime', 'event_time'):
            if key in event and event[key]:
                raw = str(event[key])
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %I:%M%p', '%Y-%m-%dT%H:%M:%S%z'):
                    try:
                        dt = datetime.strptime(raw[:19] if len(raw) > 19 else raw, fmt)
                        # FIXED: Use localize with is_dst=None
                        return NY_TZ.localize(dt, is_dst=None)
                    except ValueError:
                        continue
        return None
    except Exception:
        return None

def _is_high_impact(event: dict) -> bool:
    impact = str(event.get('impact', event.get('importance', ''))).lower()
    if impact in ('high', '3', 'red'):
        return True

    title = str(event.get('title', event.get('name', event.get('event', '')))).upper()
    return any(kw.upper() in title for kw in HIGH_IMPACT_KEYWORDS)

def _get_title(event: dict) -> str:
    return event.get('title', event.get('name', event.get('event', 'خبر مجهول')))

# ==========================================
# Display Calendar (for Dashboard)
# ==========================================
def get_upcoming_news(hours_ahead: int = 4) -> list[dict]:
    now = datetime.now(NY_TZ)
    calendar = fetch_economic_calendar()
    upcoming = []

    for event in calendar:
        if not _is_high_impact(event):
            continue
        event_time = _parse_event_time(event)
        if not event_time:
            continue
        diff = (event_time - now).total_seconds() / 3600
        if 0 <= diff <= hours_ahead:
            upcoming.append({
                'time': event_time.strftime('%H:%M'),
                'title': _get_title(event),
                'diff': f"{int(diff * 60)} دقيقة"
            })

    return sorted(upcoming, key=lambda x: x['time'])
